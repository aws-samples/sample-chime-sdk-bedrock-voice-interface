import boto3
import asyncio
import time
import os
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent
from aws_lambda_powertools import Logger

logger = Logger()

class TranscriptionResultHandler(TranscriptResultStreamHandler):       
    def __init__(self, transcript_stream):
        super().__init__(transcript_stream) 
        self.transcription_result = []

    async def handle_transcript_event(self, transcript_event: TranscriptEvent):
        results = transcript_event.transcript.results
        for result in results:
            if not result.is_partial:
                for alt in result.alternatives:
                    self.transcription_result.append(alt.transcript)

async def stream_audio(audio_data, language_code, sample_rate=8000):
    # Create streaming client
    my_region = os.environ['AWS_REGION']

    logger.info(f"Using region: {my_region}")

    client = TranscribeStreamingClient(region=my_region)


    # Start transcription stream
    stream = await client.start_stream_transcription(
        language_code=language_code,
        media_sample_rate_hz=sample_rate,
        media_encoding="pcm"
    )

    async def write_chunks():
        # Send audio chunks to the stream
        chunk_size = 1024 * 3  # 1KB chunks
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            await stream.input_stream.send_audio_event(audio_chunk=chunk)
        await stream.input_stream.end_stream()

    # Create handler instance
    handler = TranscriptionResultHandler(stream.output_stream)

    # Handle audio stream and transcription results
    await asyncio.gather(write_chunks(), handler.handle_events())

    return " ".join(handler.transcription_result)


def lambda_handler(event, context):
    try:
        # Get bucket and key from event
        bucket = event['bucket']
        key = event['key']
        language_code = event['language_code']

        logger.info(f"Received event: {event}")
        
        # Initialize S3 client
        s3_client = boto3.client('s3')
        
        # Download audio file from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        audio_data = response['Body'].read()
        
        # Run transcription
        transcription_result = asyncio.run(stream_audio(audio_data=audio_data, language_code=language_code))
        
        return {
            'statusCode': 200,
            'transcription': transcription_result
        }
        
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        raise e
