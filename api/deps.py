from __future__ import annotations

import os

import boto3
import redis
from qdrant_client import QdrantClient


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
    )


def redis_client():
    return redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


def qdrant_client() -> QdrantClient:
    return QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
