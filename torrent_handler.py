import os
import requests
import bencode
import hashlib
import threading
import time
from urllib.parse import urlparse, parse_qs
from flask import Response, stream_template

class TorrentHandler:
    def __init__(self):
        self.active_torrents = {}
        self.download_dir = "temp_torrents"
        os.makedirs(self.download_dir, exist_ok=True)
    
    def parse_magnet(self, magnet_url):
        """Parse magnet link to extract info hash and trackers"""
        try:
            parsed = urlparse(magnet_url)
            params = parse_qs(parsed.query)
            
            # Extract info hash
            xt = params.get('xt', [''])[0]
            if xt.startswith('urn:btih:'):
                info_hash = xt[9:]
            else:
                return None, []
            
            # Extract trackers
            trackers = params.get('tr', [])
            
            # Extract display name
            dn = params.get('dn', ['Unknown'])[0]
            
            return {
                'info_hash': info_hash,
                'trackers': trackers,
                'name': dn
            }, trackers
            
        except Exception as e:
            print(f"Error parsing magnet: {e}")
            return None, []
    
    def get_torrent_info_from_dht(self, info_hash):
        """Try to get torrent metadata from DHT"""
        # This is a simplified version - in production you'd use a proper DHT client
        # For now, we'll return basic info
        return {
            'name': f'Torrent_{info_hash[:8]}',
            'files': [{'name': 'video.mp4', 'length': 1000000000}]  # 1GB placeholder
        }
    
    def stream_torrent_http(self, magnet_url):
        """Create HTTP streaming endpoint for torrent"""
        torrent_info, trackers = self.parse_magnet(magnet_url)
        
        if not torrent_info:
            return None
        
        info_hash = torrent_info['info_hash']
        
        # Store the magnet URL mapping for later retrieval
        self.store_magnet_mapping(info_hash, magnet_url)
        
        print(f"Processing magnet: {magnet_url}")
        print(f"Info hash: {info_hash}")
        print(f"Trackers: {len(trackers)}")
        
        return {
            'stream_url': f'/stream_torrent/{info_hash}',
            'info': torrent_info,
            'status': 'ready'
        }
    
    def get_video_stream(self, info_hash):
        """Generate video stream for torrent"""
        # Try to get actual torrent data using the info hash
        try:
            # First check if we have the magnet URL for this info hash
            magnet_url = self.get_magnet_by_hash(info_hash)
            if not magnet_url:
                return None
            
            # Try to connect to torrent network and stream content
            return self.stream_from_torrent_network(magnet_url)
            
        except Exception as e:
            print(f"Error streaming torrent {info_hash}: {e}")
            return None
    
    def get_magnet_by_hash(self, info_hash):
        """Get original magnet URL by info hash"""
        # Store mapping of info hash to magnet URL
        if not hasattr(self, 'hash_to_magnet'):
            self.hash_to_magnet = {}
        
        return self.hash_to_magnet.get(info_hash)
    
    def store_magnet_mapping(self, info_hash, magnet_url):
        """Store mapping of info hash to magnet URL"""
        if not hasattr(self, 'hash_to_magnet'):
            self.hash_to_magnet = {}
        
        self.hash_to_magnet[info_hash] = magnet_url
    
    def stream_from_torrent_network(self, magnet_url):
        """Attempt to connect to torrent network and stream content"""
        try:
            # Parse magnet to get trackers
            torrent_info, trackers = self.parse_magnet(magnet_url)
            if not torrent_info:
                return None
            
            # Try to connect to trackers and get peer information
            peers = self.connect_to_trackers(torrent_info, trackers)
            
            if peers:
                # If we found peers, try to get file list and stream largest video file
                return self.stream_from_peers(torrent_info, peers)
            else:
                # No peers found - torrent might be dead or network issues
                print(f"No peers found for torrent: {torrent_info['name']}")
                return None
                
        except Exception as e:
            print(f"Error in torrent streaming: {e}")
            return None
    
    def connect_to_trackers(self, torrent_info, trackers):
        """Try to connect to trackers and get peer list"""
        # This is a simplified implementation
        # In a real implementation, you would:
        # 1. Send announce requests to trackers
        # 2. Parse tracker responses
        # 3. Get list of peers
        
        print(f"Attempting to connect to {len(trackers)} trackers for {torrent_info['name']}")
        
        # For now, simulate no peers found (since we don't have full BitTorrent client)
        # This is why the stream fails - we need a real torrent client library
        return []
    
    def stream_from_peers(self, torrent_info, peers):
        """Stream video content from torrent peers"""
        # This would implement the actual BitTorrent protocol
        # to download and stream video chunks from peers
        
        # For now, return None since we don't have peer connections
        return None

# Global torrent handler instance
torrent_handler = TorrentHandler()