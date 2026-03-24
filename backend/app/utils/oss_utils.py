import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict
from urllib.parse import quote

import oss2
import requests
import urllib3
from app.utils.get_sso_token import get_sso_token_sync
from oss2.models import PartInfo

logger = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sso_host = 'https://sso.openxlab.org.cn'
oss_host = 'https://cmg.openxlab.org.cn'


def _init_bucket(token, bucket_name='openxlab', endpoint='https://oss-cn-shanghai.aliyuncs.com'):
    headers = {
        'Connection': 'keep-alive',
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': token,
        'Host': 'cmg.openxlab.org.cn',
    }

    res = requests.get(
        oss_host + '/upload-service/upload/sts', headers=headers, verify=False
    )

    if res.status_code != 200:
        raise Exception('Failed to fetch STS credentials')

    sts_data = res.json()
    accessKeyId = sts_data.get('accessKeyId')
    accessKeySecret = sts_data.get('accessKeySecret')
    securityToken = sts_data.get('securityToken')

    auth = oss2.StsAuth(accessKeyId, accessKeySecret, securityToken)
    return oss2.Bucket(auth, endpoint, bucket_name)


def _multipart_upload(bucket, filepath, oss_key):
    total_size = os.path.getsize(filepath)
    if total_size == 0:
        bucket.put_object(oss_key, b'')
        return

    part_size = oss2.determine_part_size(total_size, preferred_size=1 * 1024)
    init_res = bucket.init_multipart_upload(oss_key)
    upload_id = init_res.upload_id
    parts = []

    with open(filepath, 'rb') as fileobj:
        part_number = 1
        offset = 0
        while offset < total_size:
            num_to_upload = min(part_size, total_size - offset)
            result = bucket.upload_part(
                oss_key,
                upload_id,
                part_number,
                oss2.SizedFileAdapter(fileobj, num_to_upload),
            )
            parts.append(PartInfo(part_number, result.etag))
            offset += num_to_upload
            part_number += 1

    bucket.complete_multipart_upload(oss_key, upload_id, parts)


def upload_to_oss(
    filepath,
    oss_key=None,
    token=None,
    bucket_name='openxlab',
    endpoint='https://oss-cn-shanghai.aliyuncs.com',
):
    file_name = os.path.basename(filepath)
    if oss_key is None:
        oss_key = 'test/ui_agent/' + file_name
    if token is None:
        token, cookies = get_sso_token_sync(username='web_test@pjlab.org.cn', password='Test0315')

    bucket = _init_bucket(token, bucket_name, endpoint)
    # print(f"[oss] Uploading file: {filepath} -> {oss_key}")
    _multipart_upload(bucket, filepath, oss_key)

    encoded_key = quote(oss_key, safe='/')
    oss_url = f'https://static.openxlab.org.cn/{encoded_key}'
    logger.info(f'[oss] Upload complete: {oss_url}')
    return oss_url


def upload_dir_to_oss(
    dir_path,
    oss_key_prefix=None,
    token=None,
    bucket_name='openxlab',
    endpoint='https://oss-cn-shanghai.aliyuncs.com',
    *,
    concurrency: int = 8,
):
    """Recursively upload a local directory to OSS in parallel, preserving
    relative paths.

    Returns a mapping from the relative file path to its OSS URL.
    """
    if not os.path.isdir(dir_path):
        raise ValueError(f'{dir_path} is not a directory')

    dir_name = os.path.basename(os.path.normpath(dir_path))
    if oss_key_prefix is None:
        oss_key_prefix = f'test/ui_agent/{dir_name}'
    oss_key_prefix = oss_key_prefix.rstrip('/')

    if token is None:
        token, cookies = get_sso_token_sync(username='web_test@pjlab.org.cn', password='Test0315')

    bucket = _init_bucket(token, bucket_name, endpoint)
    uploaded_files: Dict[str, str] = {}
    files_to_upload = []

    for root, _, files in os.walk(dir_path):
        for file_name in files:
            full_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(full_path, dir_path)
            posix_rel_path = rel_path.replace(os.sep, '/')
            oss_key = f'{oss_key_prefix}/{posix_rel_path}'
            files_to_upload.append((full_path, posix_rel_path, oss_key))

    if not files_to_upload:
        return uploaded_files

    def _upload_task(item):
        full_path, posix_rel_path, oss_key = item
        # print(f"[oss] Uploading file: {full_path} -> {oss_key}")
        _multipart_upload(bucket, full_path, oss_key)
        encoded_key = quote(oss_key, safe='/')
        url = f'https://static.openxlab.org.cn/{encoded_key}'
        logger.info(f'[oss] Upload complete: {url}')
        return posix_rel_path, url

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_item = {executor.submit(_upload_task, item): item for item in files_to_upload}
        for future in as_completed(future_to_item):
            rel_path, url = future.result()
            uploaded_files[rel_path] = url
            logger.info(f'[oss] Uploaded {rel_path} ({len(uploaded_files)}/{len(files_to_upload)})')

    return uploaded_files


# ---------------------------------------------------------------------------
# Provider wrapper for the providers auto-discovery mechanism.
# This class is loaded automatically when this module exists (internal deploy).
# ---------------------------------------------------------------------------

class Provider:
    """StorageProvider implementation backed by Alibaba Cloud OSS via internal STS."""

    name = 'openxlab_oss'

    def upload_report(self, local_dir: str, key_prefix: str) -> str | None:
        if not local_dir or not os.path.exists(local_dir):
            logger.warning('[OSS Provider] Report directory does not exist: %s', local_dir)
            return None

        try:
            oss_key = f'test/webqa_agent/reports/{key_prefix}'

            uploaded = upload_dir_to_oss(local_dir, oss_key_prefix=oss_key)
            if not uploaded:
                return None

            html_files = [f for f in uploaded.keys() if f.endswith('.html')]
            if html_files:
                main_html = next(
                    (f for f in html_files if 'test_report' in f or 'report' in f.lower()),
                    html_files[0],
                )
                return uploaded[main_html]

            return list(uploaded.values())[0]
        except Exception:
            logger.exception('[OSS Provider] Upload failed: local_dir=%s', local_dir)
            return None
