"""
High-performance UDP client with sliding window protocol 
for reliable file transfers with fast retransmission
"""
import os
import sys
import socket
import time
import struct
import logging
import argparse
import threading
from packet import *

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('FastClient')

# Constants
DEFAULT_TIMEOUT = 0.8  # Socket timeout in seconds
DEFAULT_CHUNK_SIZE = 65536  # 64KB - safer chunk size
DEFAULT_SOCKET_BUFFER_SIZE = 2097152  # 2MB socket buffer
DEFAULT_WINDOW_SIZE = 8  # Sliding window size (packets)
DUPLICATE_ACK_THRESHOLD = 3  # Fast retransmit after this many duplicate ACKs
MAX_RETRIES = 60  # Maximum retransmission attempts

class SlidingWindow:
    """Implements a sliding window protocol for reliable transmission"""
    
    def __init__(self, window_size=DEFAULT_WINDOW_SIZE):
        """Initialize sliding window with given size"""
        self.window_size = window_size
        self.packets = {}  # seq_num -> (packet_data, retries, timestamp)
        self.base = 0  # Base sequence number (left edge of window)
        self.next_seq = 0  # Next sequence number to use
        self.lock = threading.Lock()  # For thread safety
        self.ack_counts = {}  # seq_num -> count of duplicate ACKs
        self.last_ack = 0  # Last ACK received
        self.highest_ack = 0  # Highest ACK seen
        self.retransmit_count = 0  # Count of retransmissions for stats
        self.dup_acks = 0  # Count of duplicate ACKs for debugging
    
    def can_send(self):
        """Check if window has room for more packets"""
        with self.lock:
            return len(self.packets) < self.window_size
    
    def add_packet(self, seq_num, packet):
        """Add packet to window"""
        with self.lock:
            self.packets[seq_num] = (packet, 0, time.time())
            self.next_seq = max(self.next_seq, seq_num + 1)
            # Initialize ACK count if this is a new packet
            if seq_num not in self.ack_counts:
                self.ack_counts[seq_num] = 0
    
    def ack_received(self, ack_num):
        """
        Process ACK and slide window with improved handling of cumulative ACKs
        
        In TCP-style sliding window, ACK N means "I have received all bytes up to N-1"
        This method properly handles cumulative ACKs and tracks duplicate ACKs correctly
        """
        with self.lock:
            # Save highest ACK seen for proper window management
            self.highest_ack = max(self.highest_ack, ack_num)
            
            # Check if this is a duplicate ACK (same as last ACK)
            if ack_num == self.last_ack:
                # This is a duplicate ACK - find the first unacked packet
                if self.packets:
                    first_unacked = min(self.packets.keys())
                    # Increment counter for fast retransmit
                    self.ack_counts[first_unacked] = self.ack_counts.get(first_unacked, 0) + 1
                    self.dup_acks += 1
                    logger.debug(f"Duplicate ACK #{self.ack_counts[first_unacked]} for seq={first_unacked}")
                return  # No window sliding for duplicate ACK
            
            # This is a new ACK, save it
            self.last_ack = ack_num
            
            # Find packets to remove (cumulative ACK)
            to_remove = [seq for seq in self.packets if seq < ack_num]
            
            if to_remove:
                # Found packets to acknowledge, update base
                self.base = ack_num
                
                # Remove acknowledged packets and their ACK counters
                for seq in to_remove:
                    self.packets.pop(seq, None)
                    self.ack_counts.pop(seq, None)
                
                logger.debug(f"ACK {ack_num} removed {len(to_remove)} packets from window")
    
    def get_packets_to_retransmit(self):
        """
        Get packets that need retransmission with improved fast retransmit logic
        
        Handles both timeout-based and fast retransmission
        """
        now = time.time()
        to_retransmit = []
        
        with self.lock:
            # If window is empty, nothing to retransmit
            if not self.packets:
                return []
            
            # Sort packets by sequence number for ordered retransmission
            sorted_packets = sorted(self.packets.items())
            
            for seq, (packet, retries, timestamp) in sorted_packets:
                needs_retransmit = False
                
                # Check for fast retransmit condition - triple duplicate ACK
                if seq in self.ack_counts and self.ack_counts[seq] >= DUPLICATE_ACK_THRESHOLD:
                    # Fast retransmit - only retransmit once per triple duplicate ACK
                    needs_retransmit = True
                    logger.info(f"Fast retransmit for seq={seq} after {self.ack_counts[seq]} duplicate ACKs")
                    # Reset counter to prevent immediate re-retransmission
                    self.ack_counts[seq] = 0
                    
                # Check for timeout condition with exponential backoff
                elif now - timestamp > DEFAULT_TIMEOUT * (2 ** min(retries, 4)):
                    needs_retransmit = True
                    logger.debug(f"Timeout retransmit for seq={seq}, retry #{retries+1}")
                
                if needs_retransmit:
                    to_retransmit.append((seq, packet, retries))
                    self.packets[seq] = (packet, retries + 1, now)
                    self.retransmit_count += 1
        
        return to_retransmit
    
    def is_empty(self):
        """Check if window is empty"""
        with self.lock:
            return len(self.packets) == 0
    
    def get_failed_packets(self):
        """Get packets that have exceeded max retries"""
        failed = []
        with self.lock:
            for seq, (packet, retries, _) in list(self.packets.items()):
                if retries >= MAX_RETRIES:
                    failed.append(seq)
        return failed
    
    def get_stats(self):
        """Get window statistics for debugging and monitoring"""
        with self.lock:
            return {
                "window_size": self.window_size,
                "packets_in_flight": len(self.packets),
                "base_seq": self.base,
                "next_seq": self.next_seq,
                "retransmit_count": self.retransmit_count,
                "duplicate_acks": self.dup_acks,
                "last_ack": self.last_ack,
                "highest_ack": self.highest_ack
            }

class FastClient:
    """High-performance UDP client for fast file transfers"""
    
    def __init__(self, server_ip, server_port, chunk_size=DEFAULT_CHUNK_SIZE, 
                timeout=DEFAULT_TIMEOUT, window_size=DEFAULT_WINDOW_SIZE):
        """Initialize client with server address"""
        self.server_addr = (server_ip, server_port)
        self.chunk_size = chunk_size
        self.window_size = window_size
        
        # Create socket with optimal settings
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(timeout)
        
        # Optimize socket
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, DEFAULT_SOCKET_BUFFER_SIZE)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, DEFAULT_SOCKET_BUFFER_SIZE)
        except Exception as e:
            logger.warning(f"Failed to set socket buffer size: {e}")
        
        # Connection state
        self.seq_num = generate_initial_seq_num()
        self.ack_num = 0
        self.connected = False
        
        # Transfer state
        self.last_ack = 0
        self.window = SlidingWindow(window_size)
        self.ack_thread = None
        self.stop_event = threading.Event()
        
        logger.info(f"FastClient initialized, target: {server_ip}:{server_port}, window_size={window_size}")
    
    def connect(self):
        """Establish connection with server - enhanced with better packet loss handling"""
        initial_seq = self.seq_num
        
        # Create SYN packet
        syn_packet = create_packet(self.seq_num, 0, SYN)
        
        # Send with increasing timeout retries
        for retry in range(5):  # More retries for initial connection
            try:
                # Send SYN
                self.socket.sendto(syn_packet, self.server_addr)
                logger.info(f"Sent SYN, seq={self.seq_num}, attempt={retry+1}")
                
                # Use exponential backoff for timeout
                timeout = DEFAULT_TIMEOUT * (2 ** retry)
                self.socket.settimeout(timeout)
                
                # Wait for SYN-ACK
                response, addr = self.socket.recvfrom(TOTAL_MAX_SIZE)
                
                # Parse response with robust error handling
                server_seq = server_ack = flags = None
                
                # Try fast parsing first, then standard parsing
                try:
                    parsed = parse_packet_fast(response)
                    if parsed and len(parsed) >= 3:
                        server_seq, server_ack, flags = parsed[:3]
                except Exception as e:
                    logger.debug(f"Fast parsing failed: {e}")
                    
                if server_seq is None:
                    try:
                        parsed = parse_packet(response)
                        if parsed:
                            server_seq, server_ack, flags = parsed[:3]
                    except Exception as e:
                        logger.debug(f"Standard parsing failed: {e}")
                        continue
                
                if server_seq is None:
                    logger.warning(f"Invalid packet received, retrying {retry+1}/5")
                    continue
                
                # Validate SYN-ACK
                if flags == SYN_ACK and server_ack == initial_seq + 1:
                    # Update sequence numbers
                    self.seq_num = initial_seq + 1
                    self.ack_num = server_seq + 1
                    
                    # Send ACK to complete handshake - with multiple attempts
                    ack_sent = False
                    for ack_attempt in range(3):
                        try:
                            ack_packet = create_packet(self.seq_num, self.ack_num, ACK)
                            self.socket.sendto(ack_packet, self.server_addr)
                            ack_sent = True
                            break
                        except Exception as e:
                            logger.debug(f"ACK send error: {e}")
                            time.sleep(0.1)
                    
                    # Even if final ACK may be lost, connection is considered established
                    # Server will handle the case where it doesn't receive the final ACK
                    self.connected = True
                    logger.info(f"Connected to {self.server_addr[0]}:{self.server_addr[1]}")
                    
                    # Reset socket timeout to default
                    self.socket.settimeout(DEFAULT_TIMEOUT)
                    return True
                else:
                    logger.warning(f"Expected SYN-ACK, got flags={flags}")
            except socket.timeout:
                logger.warning(f"Timeout waiting for SYN-ACK, retry {retry+1}/5")
            except Exception as e:
                logger.error(f"Connection error: {e}")
            
            # Wait before retry with exponential backoff
            wait_time = 0.1 * (2 ** retry)
            time.sleep(wait_time)  
        
        logger.error("Failed to connect after retries")
        return False
    
    def send_file(self, file_path):
        """Send file with robust sliding window protocol and improved packet loss handling"""
        if not self.connected:
            logger.error("Not connected to server")
            return False
        
        # Verify file exists
        if not os.path.isfile(file_path):
            logger.error(f"File not found: {file_path}")
            return False
        
        try:
            # Get file info
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            logger.info(f"Sending file: {file_name} ({file_size:,} bytes) with window size {self.window_size}")
            
            # Send file metadata with improved reliability
            metadata = f"FILE:{file_name}:{file_size}".encode('utf-8')
            metadata_result = self._send_metadata_reliable(metadata)
            if not metadata_result:
                logger.error("Failed to send file metadata")
                return False
            
            # Start ACK receiver thread
            self.stop_event.clear()
            self.window = SlidingWindow(self.window_size)
            self.ack_thread = threading.Thread(target=self._ack_receiver)
            self.ack_thread.daemon = True
            self.ack_thread.start()
            
            # Send file data with sliding window
            start_time = time.time()
            bytes_sent = 0
            chunk_num = 0
            
            try:
                # Open file with buffering
                with open(file_path, 'rb', buffering=4194304) as f:
                    while bytes_sent < file_size:
                        # Check for failed packets
                        failed_packets = self.window.get_failed_packets()
                        if failed_packets:
                            logger.error(f"Some packets exceeded max retries: {failed_packets}")
                            return False
                        
                        # Wait if window is full
                        wait_start = time.time()
                        while not self.window.can_send() and self.connected:
                            time.sleep(0.01)
                            
                            # Check for failures again
                            failed_packets = self.window.get_failed_packets()
                            if failed_packets:
                                logger.error(f"Some packets exceeded max retries: {failed_packets}")
                                return False
                                
                            # Prevent infinite wait
                            if time.time() - wait_start > 10:
                                logger.error("Timeout waiting for window space")
                                return False
                        
                        # Defend against lost connection during transfer
                        if not self.connected:
                            logger.error("Connection lost during transfer")
                            return False
                        
                        # Read next chunk
                        chunk = f.read(self.chunk_size)
                        if not chunk:
                            break
                        
                        # Create packet with error handling
                        try:
                            packet = create_packet(self.seq_num, self.ack_num, PSH_ACK, chunk)
                        except Exception as e:
                            logger.error(f"Packet creation error: {e}")
                            return False
                            
                        # Handle packet sending based on whether fragmentation occurred
                        if isinstance(packet, list):
                            # Handle fragmentation with proper sequence tracking
                            for i, fragment in enumerate(packet):
                                # Extract sequence and size
                                try:
                                    frag_seq = struct.unpack("!I", fragment[:4])[0]
                                    frag_size = len(fragment) - HEADER_SIZE
                                    
                                    # Add to window and send
                                    self.window.add_packet(frag_seq, fragment)
                                    self.socket.sendto(fragment, self.server_addr)
                                    
                                    # Update sequence number
                                    self.seq_num = frag_seq + frag_size
                                    
                                    # Brief pause between fragments to reduce network congestion
                                    if i < len(packet) - 1:
                                        time.sleep(0.001)
                                except Exception as e:
                                    logger.error(f"Fragment send error: {e}")
                        else:
                            # Single packet
                            self.window.add_packet(self.seq_num, packet)
                            self.socket.sendto(packet, self.server_addr)
                            self.seq_num += len(chunk)
                        
                        # Update progress
                        bytes_sent += len(chunk)
                        chunk_num += 1
                        
                        # Log progress periodically
                        progress = (bytes_sent / file_size) * 100
                        if progress % 10 < (len(chunk) * 100 / file_size):
                            elapsed = time.time() - start_time
                            rate = bytes_sent / (elapsed * 1024) if elapsed > 0 else 0
                            logger.info(f"Progress: {progress:.1f}% ({bytes_sent:,}/{file_size:,} bytes), {rate:.2f} KB/s")
                            # Also log window stats
                            stats = self.window.get_stats()
                            logger.info(f"Window stats: {stats}")
                
                # Wait for all packets to be ACKed with improved handling
                logger.info("Waiting for final ACKs...")
                wait_start = time.time()
                last_packet_count = len(self.window.packets)
                stall_count = 0
                
                while not self.window.is_empty() and time.time() - wait_start < 30:
                    time.sleep(0.2)
                    
                    # Check for failures
                    failed_packets = self.window.get_failed_packets()
                    if failed_packets:
                        logger.error(f"Some packets exceeded max retries: {failed_packets}")
                        return False
                    
                    # Check for stall conditions - improved detection
                    current_count = len(self.window.packets)
                    if current_count == last_packet_count and current_count > 0:
                        stall_count += 1
                        if stall_count >= 15:  # 3 seconds with no progress
                            logger.warning(f"ACK progress stalled, {current_count} packets still in window")
                            # Attempt recovery by forcing retransmission
                            self._force_retransmit()
                            stall_count = 0
                    else:
                        stall_count = 0
                        last_packet_count = current_count
                    
                    # Log progress periodically
                    if current_count > 0 and time.time() - wait_start > 5:
                        logger.info(f"Still waiting for {current_count} ACKs, elapsed: {time.time() - wait_start:.1f}s")
                
                # Final check
                if not self.window.is_empty():
                    remaining = len(self.window.packets)
                    logger.error(f"Timed out waiting for {remaining} final ACKs")
                    return False
                
                # Final stats
                elapsed = time.time() - start_time
                rate = file_size / (elapsed * 1024) if elapsed > 0 else 0
                stats = self.window.get_stats()
                logger.info(f"File sent successfully: {file_size:,} bytes in {elapsed:.2f}s ({rate:.2f} KB/s)")
                logger.info(f"Final transfer stats: {stats}")
                return True
                
            finally:
                # Stop ACK receiver thread
                self.stop_event.set()
                if self.ack_thread and self.ack_thread.is_alive():
                    self.ack_thread.join(timeout=1.0)
                
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _ack_receiver(self):
        """Background thread to receive ACKs for sliding window with improved packet loss handling"""
        # Set a shorter timeout for the ACK receiver
        self.socket.settimeout(0.2)
        last_stats_time = time.time()
        
        while not self.stop_event.is_set():
            try:
                # Wait for packet
                packet, _ = self.socket.recvfrom(TOTAL_MAX_SIZE)
                
                # Parse packet with error handling
                try:
                    # Try fast parsing first
                    parsed = parse_packet_fast(packet)
                    if not parsed:
                        parsed = parse_packet(packet)
                    
                    if parsed:
                        # Extract ACK number
                        if len(parsed) == 4:  # Fast parse
                            _, ack_num, flags, _ = parsed
                        else:  # Full parse
                            _, ack_num, flags, _, _ = parsed
                        
                        # Only process ACK packets
                        if flags == ACK:
                            # Update sliding window
                            self.window.ack_received(ack_num)
                            
                            # Log window status periodically or on significant changes
                            now = time.time()
                            if now - last_stats_time > 5.0:  # Log every 5 seconds
                                stats = self.window.get_stats()
                                logger.debug(f"Window stats: {stats}")
                                last_stats_time = now
                except Exception as e:
                    logger.debug(f"Error processing ACK: {e}")
                
            except socket.timeout:
                # Normal timeout, just continue
                pass
            except Exception as e:
                if not self.stop_event.is_set():
                    logger.error(f"Error in ACK receiver: {e}")
            
            # Check for packets to retransmit
            if not self.stop_event.is_set():
                try:
                    to_retransmit = self.window.get_packets_to_retransmit()
                    for seq, packet, retries in to_retransmit:
                        if self.stop_event.is_set():
                            break
                            
                        if retries < MAX_RETRIES:
                            logger.debug(f"Retransmitting packet seq={seq} (retry {retries+1}/{MAX_RETRIES})")
                            self.socket.sendto(packet, self.server_addr)
                        else:
                            logger.warning(f"Packet seq={seq} reached max retries ({MAX_RETRIES})")
                except Exception as e:
                    logger.error(f"Error retransmitting packets: {e}")
    
    def _send_metadata_reliable(self, metadata, max_retries=5):
        """Send metadata with enhanced reliability"""
        # Create packet with push+ack flags
        packet = create_packet(self.seq_num, self.ack_num, PSH_ACK, metadata)
        data_len = len(metadata)
        
        if isinstance(packet, list):
            # Metadata too large for a single packet - rare case
            logger.warning("Metadata requires fragmentation - unusual case")
            # Fall back to simple retry mechanism for each fragment
            for i, fragment in enumerate(packet):
                frag_seq = struct.unpack("!I", fragment[:4])[0]
                frag_size = len(fragment) - HEADER_SIZE
                
                success = False
                for retry in range(max_retries):
                    try:
                        self.socket.sendto(fragment, self.server_addr)
                        logger.debug(f"Sent metadata fragment {i+1}/{len(packet)}")
                        
                        # Wait for ACK with increasing timeout
                        timeout = DEFAULT_TIMEOUT * (1 + retry * 0.5)
                        self.socket.settimeout(timeout)
                        
                        response, _ = self.socket.recvfrom(TOTAL_MAX_SIZE)
                        parsed = parse_packet_fast(response) or parse_packet(response)
                        
                        if parsed:
                            _, server_ack, flags = parsed[:3]
                            if flags == ACK and server_ack == frag_seq + frag_size:
                                # Update sequence number
                                self.seq_num = frag_seq + frag_size
                                success = True
                                break
                    except socket.timeout:
                        logger.debug(f"Timeout on metadata fragment {i+1}, retry {retry+1}")
                    except Exception as e:
                        logger.warning(f"Error sending metadata fragment: {e}")
                        
                    # Wait before retry with backoff
                    time.sleep(0.1 * (retry + 1))
                    
                if not success:
                    logger.error(f"Failed to send metadata fragment {i+1}")
                    return False
                
            return True
        else:
            # Simple retry for small, important packets
            for retry in range(max_retries):
                try:
                    self.socket.sendto(packet, self.server_addr)
                    logger.debug(f"Sent metadata, attempt {retry+1}/{max_retries}")
                    
                    # Use increasing timeout for retries
                    timeout = DEFAULT_TIMEOUT * (1 + retry * 0.5)
                    self.socket.settimeout(timeout)
                    
                    # Wait for ACK
                    response, _ = self.socket.recvfrom(TOTAL_MAX_SIZE)
                    parsed = parse_packet_fast(response) or parse_packet(response)
                    
                    if parsed:
                        _, server_ack, flags = parsed[:3]
                        if flags == ACK and server_ack == self.seq_num + data_len:
                            # Update sequence number
                            self.seq_num += data_len
                            # Reset socket timeout
                            self.socket.settimeout(DEFAULT_TIMEOUT)
                            return True
                except socket.timeout:
                    logger.warning(f"Timeout on metadata, retry {retry+1}/{max_retries}")
                except Exception as e:
                    logger.error(f"Error sending metadata: {e}")
                
                # Wait before retry with backoff
                time.sleep(0.1 * (retry + 1))
            
            # Reset socket timeout
            self.socket.settimeout(DEFAULT_TIMEOUT)
            # Failed after all retries
            return False
    
    def _force_retransmit(self):
        """
        Force retransmission of all packets in window when stalled,
        with improved ordering for better packet loss handling
        """
        try:
            retransmitted = 0
            with self.window.lock:
                # Get sorted packets for ordered retransmission - important for proper in-order delivery
                seqs = sorted(self.window.packets.keys())
                
                # Retransmit ordered packets with small delay between them
                for seq in seqs:
                    packet, retries, _ = self.window.packets[seq]
                    if retries < MAX_RETRIES:
                        self.socket.sendto(packet, self.server_addr)
                        # Update retry count and timestamp
                        self.window.packets[seq] = (packet, retries + 1, time.time())
                        retransmitted += 1
                        # Small delay between packets to reduce congestion
                        time.sleep(0.002)
            
            if retransmitted > 0:
                logger.info(f"Force retransmitted {retransmitted} packets in order")
        except Exception as e:
            logger.error(f"Error during force retransmit: {e}")
    
    def _adjust_window_size(self):
        """Dynamically adjust window size based on network conditions"""
        # Simple adjustment based on retransmissions
        with self.window.lock:
            # Count packets that needed retransmission
            retry_count = sum(1 for _, retries, _ in self.window.packets.values() if retries > 0)
            
            # Adjust window if needed
            if retry_count > self.window_size / 2:
                # High loss rate - reduce window
                new_size = max(2, self.window.window_size // 2)
                if new_size < self.window.window_size:
                    self.window.window_size = new_size
                    logger.info(f"Reduced window size to {new_size} due to packet loss")
            elif retry_count == 0 and self.window.window_size < DEFAULT_WINDOW_SIZE:
                # Low loss rate - gradually increase window
                self.window.window_size = min(DEFAULT_WINDOW_SIZE, self.window.window_size + 1)
                logger.debug(f"Increased window size to {self.window.window_size}")

    def close(self):
        """Close connection gracefully"""
        if not self.connected:
            return
        
        try:
            # Stop ACK receiver if running
            self.stop_event.set()
            if self.ack_thread and self.ack_thread.is_alive():
                self.ack_thread.join(timeout=1.0)
            
            # Send FIN
            fin_packet = create_packet(self.seq_num, self.ack_num, FIN)
            self.socket.sendto(fin_packet, self.server_addr)
            
            # Wait for FIN-ACK with short timeout
            self.socket.settimeout(0.5)
            try:
                response, _ = self.socket.recvfrom(TOTAL_MAX_SIZE)
                parsed = parse_packet_fast(response)
                if not parsed:
                    parsed = parse_packet(response)
                
                if parsed and parsed[2] == FIN_ACK:
                    # Send final ACK (no need to wait for response)
                    ack_packet = create_packet(self.seq_num + 1, parsed[0] + 1, ACK)
                    self.socket.sendto(ack_packet, self.server_addr)
            except:
                pass  # Ignore timeout
        finally:
            self.socket.close()
            self.connected = False

def main():
    """Main entry point for the client"""
    parser = argparse.ArgumentParser(description="Fast UDP file transfer client")
    parser.add_argument("server_ip", help="Server IP address")
    parser.add_argument("server_port", type=int, help="Server port")
    parser.add_argument("--file", "-f", required=True, help="File to send")
    parser.add_argument("--chunk-size", "-c", type=int, help="Chunk size in bytes")
    parser.add_argument("--window", "-w", type=int, default=DEFAULT_WINDOW_SIZE, 
                       help=f"Sliding window size (default: {DEFAULT_WINDOW_SIZE})")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    # Set log level
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # Use specified chunk size or default
    chunk_size = args.chunk_size if args.chunk_size else DEFAULT_CHUNK_SIZE
    
    # Create client
    client = FastClient(args.server_ip, args.server_port, 
                      chunk_size=chunk_size, 
                      window_size=args.window)
    start_time = time.time()
    
    try:
        if client.connect():
            if client.send_file(args.file):
                elapsed = time.time() - start_time
                file_size = os.path.getsize(args.file)
                rate = file_size / (elapsed * 1024) if elapsed > 0 else 0
                print(f"\nTransfer complete: {file_size:,} bytes in {elapsed:.2f}s ({rate:.2f} KB/s)")
                return 0
            else:
                print(f"\nTransfer failed after {time.time() - start_time:.2f}s")
                return 1
        else:
            print("\nConnection failed")
            return 1
    finally:
        client.close()

if __name__ == "__main__":
    sys.exit(main())