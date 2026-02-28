import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
import xml.etree.ElementTree as ET
from xml.dom import minidom

logger = logging.getLogger(__name__)

class GospelPodcastPublisher:
    """Multi-language podcast publisher with Firebase Storage and RSS feed.
    Uses per-language storage prefixes and bucket configuration.
    """

    def __init__(self, config_path: str):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        self.podcast_info = self.config.get('podcast_info', {})
        # Allow env override for bucket to support Cloud Run/Server deployments
        self.bucket_name = self.config.get('bucket_name') or os.environ.get('FIREBASE_BUCKET')
        if (not self.bucket_name) or (self.bucket_name == 'YOUR-FIREBASE-BUCKET'):
            self.bucket_name = os.environ.get('FIREBASE_BUCKET', self.config.get('bucket_name'))
        self.storage_prefix = self.config.get('storage_prefix', 'gospel/en')
        self.language = self.config.get('language', 'en')
        self.rss_blob_path = f"{self.storage_prefix}/podcast_feed.xml"
        # Email: env var takes priority over config (keep config clean for public repos)
        env_email = os.environ.get('PODCAST_EMAIL', '')
        if env_email:
            self.podcast_info['email'] = env_email
        self._firebase_init_done = False
        self.episodes: List[Dict[str, Any]] = []

    def _init_firebase(self):
        if self._firebase_init_done:
            return
        import firebase_admin
        from firebase_admin import credentials, storage
        if not firebase_admin._apps:
            # Prefer service account key if present; otherwise use ADC (Cloud Run/Server)
            cred_path = os.path.join(os.path.dirname(__file__), 'serviceAccountKey.json')
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred, {
                    'storageBucket': self.bucket_name
                })
            else:
                # Initialize with default credentials; storageBucket required
                firebase_admin.initialize_app(options={
                    'storageBucket': self.bucket_name
                })
        self.storage = storage
        self._firebase_init_done = True

    def upload_audio(self, audio_path: str) -> Optional[str]:
        try:
            self._init_firebase()
            bucket = self.storage.bucket()
            filename = os.path.basename(audio_path)
            blob_path = f"{self.storage_prefix}/podcast_audio/{filename}"
            blob = bucket.blob(blob_path)
            blob.upload_from_filename(audio_path, content_type='audio/mpeg')
            blob.make_public()
            return blob.public_url
        except Exception as e:
            logger.error(f"Firebase upload failed: {e}")
            return None

    def add_episode(self, audio_url: str, title: str, description: str, duration: int = 0,
                    pub_date: str = '', guid: str = ''):
        if not pub_date:
            pub_date = datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
        if not guid:
            guid = f"{self.podcast_info.get('website', '')}/episode/{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.episodes.insert(0, {
            'title': title,
            'description': description,
            'audio_url': audio_url,
            'pub_date': pub_date,
            'guid': guid,
            'duration': duration
        })

    def _sanitize(self, s: str) -> str:
        import re
        s = s or ''
        s = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", s)
        try:
            s = re.sub(r"[\U0001F300-\U0001FAFF]", "", s)
            s = re.sub(r"[\U0001F600-\U0001F64F]", "", s)
        except re.error:
            pass
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def generate_rss(self) -> str:
        rss = ET.Element('rss', {
            'version': '2.0',
            'xmlns:itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd',
            'xmlns:content': 'http://purl.org/rss/1.0/modules/content/',
            'xmlns:atom': 'http://www.w3.org/2005/Atom'
        })
        channel = ET.SubElement(rss, 'channel')
        ET.SubElement(channel, 'title').text = self.podcast_info.get('title', 'Daily Gospel')
        ET.SubElement(channel, 'description').text = self.podcast_info.get('description', 'Daily Gospel readings')
        ET.SubElement(channel, 'link').text = self.podcast_info.get('website', '')
        ET.SubElement(channel, 'language').text = self.language
        ET.SubElement(channel, 'itunes:author').text = self.podcast_info.get('author', '')
        ET.SubElement(channel, 'itunes:summary').text = self.podcast_info.get('description', '')
        ET.SubElement(channel, 'itunes:explicit').text = 'no'
        ET.SubElement(channel, 'itunes:category', {'text': 'Religion & Spirituality'})
        owner_email = self.podcast_info.get('email', '')
        if owner_email:
            owner = ET.SubElement(channel, 'itunes:owner')
            ET.SubElement(owner, 'itunes:name').text = self.podcast_info.get('author', 'Vatican News')
            ET.SubElement(owner, 'itunes:email').text = owner_email
            ET.SubElement(channel, 'managingEditor').text = owner_email
        cover_art_url = self.podcast_info.get('cover_art', '')
        if cover_art_url:
            ET.SubElement(channel, 'itunes:image', {'href': cover_art_url})
            image = ET.SubElement(channel, 'image')
            ET.SubElement(image, 'url').text = cover_art_url
            ET.SubElement(image, 'title').text = self.podcast_info.get('title', 'Daily Gospel')
            ET.SubElement(image, 'link').text = self.podcast_info.get('website', '')
        rss_url = self.podcast_info.get('rss_url', '')
        if rss_url:
            ET.SubElement(channel, '{http://www.w3.org/2005/Atom}link', {
                'href': rss_url,
                'rel': 'self',
                'type': 'application/rss+xml'
            })
        for ep in self.episodes:
            item = ET.SubElement(channel, 'item')
            ET.SubElement(item, 'title').text = self._sanitize(ep['title'])
            ET.SubElement(item, 'description').text = self._sanitize(ep['description'])
            ET.SubElement(item, 'itunes:summary').text = self._sanitize(ep['description'])
            ET.SubElement(item, 'pubDate').text = ep['pub_date']
            ET.SubElement(item, 'guid', {'isPermaLink': 'false'}).text = ep['guid']
            ET.SubElement(item, 'link').text = ep['audio_url']
            ET.SubElement(item, 'enclosure', {
                'url': ep['audio_url'],
                'type': 'audio/mpeg',
                'length': '1'
            })
            if ep.get('duration', 0) > 0:
                ET.SubElement(item, 'itunes:duration').text = str(ep['duration'])
        xml_str = ET.tostring(rss, encoding='utf-8')
        dom = minidom.parseString(xml_str)
        pretty = dom.toprettyxml(indent='  ', encoding='utf-8')
        out_path = os.path.join(os.path.dirname(__file__), 'podcast_feed_tmp.xml')
        with open(out_path, 'wb') as f:
            f.write(pretty)
        return out_path

    def upload_rss(self, rss_local_path: str) -> bool:
        try:
            self._init_firebase()
            bucket = self.storage.bucket()
            blob = bucket.blob(self.rss_blob_path)
            blob.upload_from_filename(rss_local_path, content_type='application/rss+xml; charset=utf-8')
            blob.make_public()
            return True
        except Exception as e:
            logger.error(f"RSS upload failed: {e}")
            return False

    def rebuild_from_storage(self, max_items: int = 10) -> Optional[str]:
        try:
            self._init_firebase()
            bucket = self.storage.bucket()
            blobs = bucket.list_blobs(prefix=f"{self.storage_prefix}/podcast_audio/")
            episodes: List[Dict[str, Any]] = []
            for b in blobs:
                if b.name.endswith('.mp3'):
                    filename = os.path.basename(b.name)
                    title = filename
                    if '_azure_' in filename:
                        title = filename.split('_azure_')[0].strip() or filename
                    episodes.append({
                        'filename': filename,
                        'size': b.size or 0,
                        'date': b.updated.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'title': self._sanitize(title)
                    })
            episodes.sort(key=lambda e: e['date'], reverse=True)
            self.episodes = []
            for ep in episodes[:max_items]:
                audio_url = f"https://storage.googleapis.com/{self.bucket_name}/{self.storage_prefix}/podcast_audio/{filename_encode(ep['filename'])}"
                self.add_episode(audio_url, ep['title'], f"Episode: {ep['title']}")
            rss_path = self.generate_rss()
            self.upload_rss(rss_path)
            return rss_path
        except Exception as e:
            logger.error(f"Rebuild failed: {e}")
            return None


def filename_encode(name: str) -> str:
    from urllib.parse import quote
    return quote(name)
