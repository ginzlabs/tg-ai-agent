import asyncio
from typing import Dict, Any, Optional
from utils.logger import logger

async def transcribe_audio(audio_url: str, language: str = "en") -> Dict[str, Any]:
    """
    Transcribe audio from the given URL.
    Simulates a task that takes 30 seconds to complete.
    
    Args:
        audio_url: URL of the audio file to transcribe
        language: Language code for transcription (default: "en")
        
    Returns:
        Dict containing the transcription result
    """
    logger.info(f"Starting transcription of {audio_url} in language {language}")
    
    # Simulate processing time (30 seconds)
    await asyncio.sleep(30)
    
    # Simulate different transcription results based on audio URL
    # In a real implementation, this would process the actual audio file
    sample_transcriptions = {
        "short": {
            "text": "This is a short audio transcription example.",
            "confidence": 0.95,
            "duration": "00:00:15",
            "language": language,
            "segments": [
                {
                    "start": 0.0,
                    "end": 15.0,
                    "text": "This is a short audio transcription example."
                }
            ]
        },
        "long": {
            "text": "This is a longer audio transcription example with multiple segments. " +
                   "It demonstrates how we handle longer audio files with multiple speakers.",
            "confidence": 0.92,
            "duration": "00:02:30",
            "language": language,
            "segments": [
                {
                    "start": 0.0,
                    "end": 30.0,
                    "text": "This is a longer audio transcription example with multiple segments."
                },
                {
                    "start": 30.0,
                    "end": 60.0,
                    "text": "It demonstrates how we handle longer audio files with multiple speakers."
                }
            ],
            "speakers": ["Speaker 1", "Speaker 2"]
        }
    }
    
    # Determine which sample to use based on URL
    is_long = "long" in audio_url.lower()
    transcription = sample_transcriptions["long" if is_long else "short"]
    
    # Add metadata
    result = {
        "transcription": transcription,
        "metadata": {
            "original_audio_url": audio_url,
            "processing_time": "30 seconds",
            "word_count": len(transcription["text"].split()),
            "source_language": language
        }
    }
    
    logger.info(f"Completed transcription of {audio_url}")
    return result 