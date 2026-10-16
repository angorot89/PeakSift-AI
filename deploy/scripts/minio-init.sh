#!/bin/sh
# Create the PRIVATE media bucket and an application user limited to it (idempotent).
set -eu
mc alias set root http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
mc mb --ignore-existing "root/$S3_BUCKET" >/dev/null
mc anonymous set none "root/$S3_BUCKET" >/dev/null   # never public
cat > /tmp/peaksift-policy.json <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
     "Resource": ["arn:aws:s3:::$S3_BUCKET"]},
    {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject",
      "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
     "Resource": ["arn:aws:s3:::$S3_BUCKET/*"]}
  ]
}
POLICY
mc admin policy create root peaksift-app /tmp/peaksift-policy.json >/dev/null 2>&1 || true
mc admin user add root "$S3_APP_ACCESS_KEY" "$S3_APP_SECRET_KEY" >/dev/null
mc admin policy attach root peaksift-app --user "$S3_APP_ACCESS_KEY" >/dev/null 2>&1 || true
# Multipart uploads abandoned by a crashed worker are removed by MinIO itself after 24 h
# (its default stale-upload expiry); on AWS, add an AbortIncompleteMultipartUpload rule.
echo "bucket $S3_BUCKET ready (private; application user limited to it)"
