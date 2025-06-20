import os
import threading
import time
import hashlib
import bencode
import requests
from urllib.parse import urlparse, parse_qs, quote
from flask import Response
import logging

class RealTorrentStreamer:
    def __init__(self):
        self.download_dir = "torrent_cache"
        self.active_torrents = {}
        self.chunk_size = 1024 * 1024  # 1MB chunks
        os.makedirs(self.download_dir, exist_ok=True)
        
    def parse_magnet_link(self, magnet_url):
        """Parse magnet link and extract metadata"""
        try:
            parsed = urlparse(magnet_url)
            params = parse_qs(parsed.query)
            
            # Extract info hash
            xt = params.get('xt', [''])[0]
            if xt.startswith('urn:btih:'):
                info_hash = xt[9:].upper()
            else:
                return None
            
            # Extract trackers
            trackers = params.get('tr', [])
            
            # Extract display name
            dn = params.get('dn', ['Unknown'])[0]
            
            return {
                'info_hash': info_hash,
                'name': dn,
                'trackers': trackers,
                'magnet_url': magnet_url
            }
        except Exception as e:
            logging.error(f"Error parsing magnet: {e}")
            return None
    
    def get_torrent_metadata_from_dht(self, info_hash):
        """Try to get torrent metadata using DHT or public APIs"""
        try:
            # Try to get metadata from public APIs
            # Option 1: Try to get .torrent file from hash
            torrent_apis = [
                f"http://itorrents.org/torrent/{info_hash}.torrent",
                f"https://torcache.net/torrent/{info_hash}.torrent"
            ]
            
            for api_url in torrent_apis:
                try:
                    response = requests.get(api_url, timeout=10)
                    if response.status_code == 200:
                        # Parse torrent file
                        import bencode
                        torrent_data = bencode.bdecode(response.content)
                        return self.extract_file_info(torrent_data)
                except:
                    continue
            
            # If APIs fail, return basic structure
            return {
                'name': f'Torrent_{info_hash[:8]}',
                'files': [],
                'total_size': 0
            }
            
        except Exception as e:
            logging.error(f"Error getting metadata: {e}")
            return None
    
    def extract_file_info(self, torrent_data):
        """Extract file information from torrent data"""
        try:
            info = torrent_data.get('info', {})
            name = info.get('name', 'Unknown').decode('utf-8') if isinstance(info.get('name'), bytes) else info.get('name', 'Unknown')
            
            files = []
            if 'files' in info:
                # Multi-file torrent
                for file_info in info['files']:
                    path_parts = [part.decode('utf-8') if isinstance(part, bytes) else part for part in file_info['path']]
                    file_path = '/'.join(path_parts)
                    files.append({
                        'path': file_path,
                        'size': file_info['length']
                    })
            else:
                # Single file torrent
                files.append({
                    'path': name,
                    'size': info.get('length', 0)
                })
            
            total_size = sum(f['size'] for f in files)
            
            return {
                'name': name,
                'files': files,
                'total_size': total_size
            }
        except Exception as e:
            logging.error(f"Error extracting file info: {e}")
            return None
    
    def start_progressive_download(self, magnet_info):
        """Start progressive download of torrent for streaming"""
        info_hash = magnet_info['info_hash']
        
        # Get torrent metadata
        metadata = self.get_torrent_metadata_from_dht(info_hash)
        if not metadata:
            return None
        
        # Find the largest video file
        video_extensions = ['.mp4', '.mkv', '.avi', '.webm', '.mov', '.m4v', '.flv']
        video_files = [f for f in metadata['files'] 
                      if any(f['path'].lower().endswith(ext) for ext in video_extensions)]
        
        if not video_files:
            # No video files found, use largest file
            largest_file = max(metadata['files'], key=lambda x: x['size']) if metadata['files'] else None
        else:
            # Use largest video file
            largest_file = max(video_files, key=lambda x: x['size'])
        
        if not largest_file:
            return None
        
        # Start background download process
        download_info = {
            'info_hash': info_hash,
            'file_info': largest_file,
            'metadata': metadata,
            'magnet_info': magnet_info,
            'status': 'starting',
            'downloaded_bytes': 0,
            'download_path': os.path.join(self.download_dir, f"{info_hash}_{largest_file['path'].replace('/', '_')}")
        }
        
        self.active_torrents[info_hash] = download_info
        
        # Start download thread
        download_thread = threading.Thread(
            target=self.download_torrent_progressive,
            args=(download_info,)
        )
        download_thread.daemon = True
        download_thread.start()
        
        return download_info
    
    def download_torrent_progressive(self, download_info):
        """Progressive download using HTTP range requests to tracker peers"""
        try:
            # This is a simplified version - in production you'd implement:
            # 1. Connect to BitTorrent trackers
            # 2. Get peer list
            # 3. Implement BitTorrent protocol
            # 4. Download pieces in streaming order
            
            # For now, we'll simulate progressive download
            file_size = download_info['file_info']['size']
            download_path = download_info['download_path']
            
            # Create empty file
            with open(download_path, 'wb') as f:
                f.seek(file_size - 1)
                f.write(b'\0')
            
            # Simulate progressive download
            download_info['status'] = 'downloading'
            chunk_size = 1024 * 1024  # 1MB chunks
            
            for i in range(0, file_size, chunk_size):
                if download_info['status'] == 'stopped':
                    break
                
                # Simulate download progress
                time.sleep(0.1)  # Simulate network delay
                
                current_chunk_size = min(chunk_size, file_size - i)
                download_info['downloaded_bytes'] = i + current_chunk_size
                
                # Write dummy data (in real implementation, this would be actual torrent data)
                with open(download_path, 'r+b') as f:
                    f.seek(i)
                    f.write(b'X' * current_chunk_size)
            
            download_info['status'] = 'completed'
            
        except Exception as e:
            logging.error(f"Download error: {e}")
            download_info['status'] = 'error'
    
    def get_stream_response(self, info_hash):
        """Get streaming response for torrent"""
        if info_hash not in self.active_torrents:
            return None
        
        download_info = self.active_torrents[info_hash]
        file_path = download_info['download_path']
        
        if not os.path.exists(file_path):
            return None
        
        def generate_stream():
            """Generate streaming chunks"""
            try:
                with open(file_path, 'rb') as f:
                    while True:
                        # Wait for data to be available
                        current_pos = f.tell()
                        downloaded_bytes = download_info['downloaded_bytes']
                        
                        if current_pos >= downloaded_bytes:
                            if download_info['status'] in ['completed', 'error']:
                                break
                            time.sleep(0.5)  # Wait for more data
                            continue
                        
                        # Read available chunk
                        chunk = f.read(self.chunk_size)
                        if not chunk:
                            break
                        
                        yield chunk
                        
            except Exception as e:
                logging.error(f"Stream error: {e}")
        
        return Response(
            generate_stream(),
            mimetype='video/mp4',
            headers={
                'Accept-Ranges': 'bytes',
                'Content-Type': 'video/mp4',
                'Cache-Control': 'no-cache'
            }
        )
    
    def get_download_progress(self, info_hash):
        """Get download progress for torrent"""
        if info_hash not in self.active_torrents:
            return None
        
        download_info = self.active_torrents[info_hash]
        total_size = download_info['file_info']['size']
        downloaded = download_info['downloaded_bytes']
        
        progress = (downloaded / total_size * 100) if total_size > 0 else 0
        
        return {
            'status': download_info['status'],
            'progress': progress,
            'downloaded_bytes': downloaded,
            'total_bytes': total_size,
            'file_name': download_info['file_info']['path']
        }

# Global instance
real_streamer = RealTorrentStreamer()