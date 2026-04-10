import hashlib
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Optional

import librosa
import numpy as np
import soundfile as sf

from app.config import settings


AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
FINGERPRINT_N_FFT = 2048
FINGERPRINT_HOP_LENGTH = 512
FINGERPRINT_PEAKS_PER_FRAME = 3
FINGERPRINT_TARGET_ZONE = 24
FINGERPRINT_FAN_VALUE = 5
FINGERPRINT_MIN_DB = -35.0


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def detect_media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    raise ValueError(f"Formato no soportado: {suffix or 'desconocido'}")


def ensure_storage_dirs() -> None:
    settings.ads_dir.mkdir(parents=True, exist_ok=True)
    settings.normalized_dir.mkdir(parents=True, exist_ok=True)
    settings.monitoring_dir.mkdir(parents=True, exist_ok=True)
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)


def save_uploaded_file(source_file, destination: Path) -> None:
    ensure_storage_dirs()
    with destination.open("wb") as target:
        shutil.copyfileobj(source_file.file, target)


def normalize_media_to_wav(source_path: Path, destination_path: Path, media_type: str) -> None:
    ensure_storage_dirs()
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no esta instalado o no esta disponible en PATH.")

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-ac",
        "1",
        "-ar",
        str(settings.sample_rate),
        str(destination_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() or "Error desconocido en ffmpeg."
        raise RuntimeError(f"No se pudo normalizar el archivo {media_type}: {stderr}")


def load_audio_features(normalized_audio_path: Path) -> tuple[np.ndarray, int]:
    samples, sample_rate = librosa.load(normalized_audio_path, sr=settings.sample_rate, mono=True)
    return samples, sample_rate


def audio_feature_vector(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    if samples.size == 0:
        return np.zeros(32, dtype=np.float32)

    mfcc = librosa.feature.mfcc(y=samples, sr=sample_rate, n_mfcc=13)
    spectral_centroid = librosa.feature.spectral_centroid(y=samples, sr=sample_rate)
    spectral_bandwidth = librosa.feature.spectral_bandwidth(y=samples, sr=sample_rate)
    zero_crossing_rate = librosa.feature.zero_crossing_rate(y=samples)
    rms = librosa.feature.rms(y=samples)

    features = np.concatenate(
        [
            mfcc.mean(axis=1),
            mfcc.std(axis=1),
            spectral_centroid.mean(axis=1),
            spectral_centroid.std(axis=1),
            spectral_bandwidth.mean(axis=1),
            spectral_bandwidth.std(axis=1),
            zero_crossing_rate.mean(axis=1),
            zero_crossing_rate.std(axis=1),
            rms.mean(axis=1),
            rms.std(axis=1),
        ]
    )
    return features.astype(np.float32)


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = np.linalg.norm(left)
    right_norm = np.linalg.norm(right)
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


def compute_fingerprint(normalized_audio_path: Path) -> tuple[str, Optional[float]]:
    samples, sample_rate = load_audio_features(normalized_audio_path)
    if samples.size == 0:
        return "", None

    duration = round(len(samples) / sample_rate, 2)
    spectral = np.abs(librosa.stft(samples, n_fft=2048, hop_length=512))
    band_energy = spectral.mean(axis=1)
    reduced = np.round(band_energy[:128], 4).astype(np.float32).tobytes()
    digest = hashlib.sha256(reduced).hexdigest()
    return digest, duration


def persist_normalized_waveform(source_path: Path) -> None:
    samples, _ = librosa.load(source_path, sr=settings.sample_rate, mono=True)
    sf.write(source_path, samples, settings.sample_rate)


def build_constellation_hashes(samples: np.ndarray, sample_rate: int) -> dict[str, list[int]]:
    """
    Genera una huella tipo constellation map.

    Cada hash representa una relacion estable entre dos picos del espectro:
    frecuencia de ancla, frecuencia objetivo y distancia temporal.
    """
    if samples.size == 0:
        return {}

    spectrogram = np.abs(
        librosa.stft(
            samples,
            n_fft=FINGERPRINT_N_FFT,
            hop_length=FINGERPRINT_HOP_LENGTH,
        )
    )
    spectrogram_db = librosa.amplitude_to_db(spectrogram + 1e-10, ref=np.max)

    peaks: list[tuple[int, int]] = []
    total_frames = spectrogram_db.shape[1]
    for frame_index in range(total_frames):
        frame = spectrogram_db[:, frame_index]
        candidate_indexes = np.argpartition(frame, -FINGERPRINT_PEAKS_PER_FRAME)[-FINGERPRINT_PEAKS_PER_FRAME:]
        ordered_indexes = candidate_indexes[np.argsort(frame[candidate_indexes])[::-1]]

        # Nos quedamos con los picos mas fuertes de cada frame para reducir ruido.
        for frequency_bin in ordered_indexes:
            if frame[frequency_bin] < FINGERPRINT_MIN_DB:
                continue
            peaks.append((frame_index, int(frequency_bin)))

    hashes: dict[str, list[int]] = defaultdict(list)
    total_peaks = len(peaks)
    for anchor_index, (anchor_time, anchor_frequency) in enumerate(peaks):
        pair_count = 0
        for target_index in range(anchor_index + 1, total_peaks):
            target_time, target_frequency = peaks[target_index]
            delta_time = target_time - anchor_time

            # El hash solo mira relaciones temporales cercanas para mantener estabilidad.
            if delta_time <= 0:
                continue
            if delta_time > FINGERPRINT_TARGET_ZONE:
                break

            # Cada hash sintetiza una "forma" chiquita del audio que luego se puede buscar.
            hash_key = f"{anchor_frequency}:{target_frequency}:{delta_time}"
            hashes[hash_key].append(anchor_time)
            pair_count += 1
            if pair_count >= FINGERPRINT_FAN_VALUE:
                break

    return dict(hashes)


def build_constellation_hashes_from_file(normalized_audio_path: Path) -> tuple[dict[str, list[int]], float]:
    samples, sample_rate = load_audio_features(normalized_audio_path)
    duration_seconds = len(samples) / sample_rate if sample_rate else 0.0
    return build_constellation_hashes(samples, sample_rate), duration_seconds
