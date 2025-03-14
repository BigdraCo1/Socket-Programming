import hashlib
import struct
import random
import logging
import time

logger = logging.getLogger('Packet')

# Define flags as byte values for direct comparison
SYN = 0x02  # b'\x02'It Naya and me and handshake me said he hit me and more
ACK = 0x10  # b'\x10'
FIN = 0x01  # b'\x01'
RST = 0x04  # b'\x04'
PSH = 0x08  # b'\x08'
URG = 0x20  # b'\x20'
ECE = 0x40  # b'\x40'
CWR = 0x80  # b'\x80'
MOR = 0x40  # More fragments flag (reusing ECE bit position)

# Combined flag constants for common operations (pre-computed)
SYN_ACK = SYN | ACK  # b'\x12'
FIN_ACK = FIN | ACK  # b'\x11'
PSH_ACK = PSH | ACK  # b'\x18'

# Packet structure constants
SEQUENCE_NUM_SIZE = 4
ACK_NUM_SIZE = 4
FLAGS_SIZE = 1
CHECKSUM_SIZE = 16
HEADER_SIZE = SEQUENCE_NUM_SIZE + ACK_NUM_SIZE + FLAGS_SIZE + CHECKSUM_SIZE
TOTAL_MAX_SIZE = 1500  # Maximum total packet size (including header)
PAYLOAD_MAX_SIZE = TOTAL_MAX_SIZE - HEADER_SIZE  # Maximum payload size

# Flag bit masks - stored as bytes for direct matching
FLAG_MASKS = {
    'SYN': bytes([SYN]),
    'ACK': bytes([ACK]),
    'FIN': bytes([FIN]),
    'RST': bytes([RST]),
    'PSH': bytes([PSH]),
    'URG': bytes([URG]),
    'ECE': bytes([ECE]),
    'MOR': bytes([MOR]),
    'CWR': bytes([CWR]),
    'SYN_ACK': bytes([SYN_ACK]),
    'FIN_ACK': bytes([FIN_ACK])
}

def flags_to_str(flags_byte):
    """
    Convert flags byte to string representation
    
    Optimized implementation using pre-computed tables
    """
    if isinstance(flags_byte, int):
        flags_byte = bytes([flags_byte])  # Convert to bytes if needed
        
    # Fast path for common flag combinations
    if flags_byte == FLAG_MASKS['SYN_ACK']:
        return "SYN+ACK"
    elif flags_byte == FLAG_MASKS['FIN_ACK']:
        return "FIN+ACK" 
    elif flags_byte == FLAG_MASKS['SYN']:
        return "SYN"
    elif flags_byte == FLAG_MASKS['ACK']:
        return "ACK"
    elif flags_byte == FLAG_MASKS['FIN']:
        return "FIN"
        
    # Slower path for other combinations
    flags_int = flags_byte[0]
    result = []
    if flags_int & FIN: result.append("FIN")
    if flags_int & SYN: result.append("SYN") 
    if flags_int & RST: result.append("RST")
    if flags_int & PSH: result.append("PSH")
    if flags_int & ACK: result.append("ACK")
    if flags_int & URG: result.append("URG")
    if flags_int & ECE or flags_int & MOR: 
        if flags_int & MOR:
            result.append("MOR")  # Show as MOR if used for fragmentation
        else:
            result.append("ECE")
    if flags_int & CWR: result.append("CWR")
    
    return "+".join(result) if result else "NONE"

def has_flag(flags_byte, flag):
    """
    Check if a specific flag is set
    
    Optimized implementation using direct bitwise AND
    
    Args:
        flags_byte: The flags byte to check
        flag: The flag bit to check for (e.g. SYN, ACK)
        
    Returns:
        bool: True if the flag is set, False otherwise
    """
    if isinstance(flags_byte, bytes) and len(flags_byte) == 1:
        return (flags_byte[0] & flag) == flag
    else:
        return (flags_byte & flag) == flag

def is_more_fragments(flags):
    """Check if the MOR (more fragments) flag is set"""
    return (flags & MOR) == MOR

def calculate_checksum(data):
    """Calculate a 16-byte MD5 checksum"""
    return hashlib.md5(data).digest()

# Increase the max fragment age to handle packet loss scenarios
MAX_FRAGMENT_AGE = 120  # Maximum age for fragments in seconds

# Add an optional retry mechanism for checksum verification 
def verify_checksum(data, checksum, retry=1):
    """
    Verify the checksum of a packet with optional retry for improved reliability
    
    Args:
        data: The data to verify
        checksum: The checksum to compare against
        retry: Number of verification attempts for border cases
        
    Returns:
        bool: True if checksum matches, False otherwise
    """
    # First fast check
    calc_checksum = calculate_checksum(data)
    if calc_checksum == checksum:
        return True
        
    # If failed and retry > 0, try again (helps with bit flips/CPU timing issues)
    if retry > 0:
        time.sleep(0.001)  # Tiny sleep to ensure different CPU state
        calc_checksum = calculate_checksum(data)
        return calc_checksum == checksum
        
    return False

def create_packet(seq_num, ack_num, flags, payload=b''):
    """
    Create a packet with the given parameters - optimization for performance
    
    If payload is larger than PAYLOAD_MAX_SIZE, it will be fragmented into
    multiple packets, with the MOR (more fragments) flag set on all but the last packet.
    """
    # Check if fragmentation is needed
    if len(payload) <= PAYLOAD_MAX_SIZE:
        # No fragmentation needed
        header_without_checksum = struct.pack("!IIB", seq_num, ack_num, flags)
        checksum = calculate_checksum(header_without_checksum + payload)
        return header_without_checksum + checksum + payload
    else:
        # Fragmentation needed
        fragments = []
        total_bytes = len(payload)
        
        # Calculate fragments with slightly smaller max size for greater reliability
        adjusted_max_size = PAYLOAD_MAX_SIZE - 16  # Smaller fragments for more reliable delivery
        fragment_count = (total_bytes + adjusted_max_size - 1) // adjusted_max_size
        
        logger.debug(f"Fragmenting packet: {total_bytes} bytes into {fragment_count} fragments")
        
        for i in range(fragment_count):
            # Calculate start and end positions for this fragment
            start = i * adjusted_max_size
            end = min(start + adjusted_max_size, total_bytes)
            fragment_data = payload[start:end]
            
            # Calculate fragment sequence number based on original seq_num and position
            fragment_seq = seq_num + start
            
            # Set flags for this fragment
            fragment_flags = flags
            
            # All fragments except the last one have the MOR flag
            if i < fragment_count - 1:
                fragment_flags |= MOR
            
            # Create fragment packet
            header_without_checksum = struct.pack("!IIB", fragment_seq, ack_num, fragment_flags)
            checksum = calculate_checksum(header_without_checksum + fragment_data)
            fragment = header_without_checksum + checksum + fragment_data
            
            fragments.append(fragment)
            
        return fragments

def create_packets_from_data(seq_num, ack_num, flags, data):
    """
    Helper function to create a list of packets from data with automatic fragmentation
    
    Args:
        seq_num: Starting sequence number
        ack_num: Acknowledgment number
        flags: Control flags
        data: Data to send
        
    Returns:
        List of packet bytes
    """
    packets = create_packet(seq_num, ack_num, flags, data)
    if isinstance(packets, list):
        return packets
    else:
        return [packets]  # Single packet, wrap in list

def parse_packet(packet):
    """
    Parse a packet into its components - optimized for reliability
    
    Returns:
    (seq_num, ack_num, flags, checksum, payload) or None if invalid
    """
    # Check minimum size
    if len(packet) < HEADER_SIZE:
        return None
    
    try:
        # Fast extraction of header fields with direct slicing
        header_part = packet[:9]
        seq_num, ack_num, flags = struct.unpack("!IIB", header_part)
        
        # Extract checksum using direct slicing
        checksum = packet[9:25]
        
        # Extract payload using direct slicing
        payload = packet[25:]
        
        # Verify checksum with retry for resilience
        if not verify_checksum(header_part + payload, checksum, retry=2):
            # Try one more approach - recompute with padded data if payload is uneven length
            if len(payload) % 2 != 0:
                padded_payload = payload + b'\x00'  # Add padding byte
                if not verify_checksum(header_part + padded_payload, checksum, retry=1):
                    return None
            else:
                return None
            
        return seq_num, ack_num, flags, checksum, payload
    except Exception:
        # Catch any parsing errors
        return None

def is_more_fragments(flags):
    """
    Check if the MOR (more fragments) flag is set
    
    Args:
        flags: The flags byte
        
    Returns:
        bool: True if more fragments flag is set
    """
    return (flags & MOR) == MOR

def generate_initial_seq_num():
    """Generate a random initial sequence number - optimized"""
    # Use os.urandom for better randomness if needed
    return random.randint(0, 2**32 - 1)

# Pre-compute common packet templates for frequently used packet types
SYN_PACKET_TEMPLATE = struct.pack("!IIB", 0, 0, SYN)  # Just add seq_num and checksum
ACK_PACKET_TEMPLATE = struct.pack("!IIB", 0, 0, ACK)  # Just add seq_num, ack_num and checksum
SYN_ACK_PACKET_TEMPLATE = struct.pack("!IIB", 0, 0, SYN_ACK)  # Just add seq_num, ack_num and checksum

# Add fast verification option to skip intensive checksums when reliability is less critical
def fast_verify_checksum(data, checksum):
    """Quick checksum verification for time-critical operations"""
    # Only check first 4 bytes for speed
    return calculate_checksum(data)[:4] == checksum[:4]

def parse_packet_fast(packet):
    """
    Parse a packet with minimal validation for speed-critical paths
    
    Returns:
    (seq_num, ack_num, flags, payload) or None if invalid
    """
    # Check minimum size
    if len(packet) < HEADER_SIZE:
        return None
    
    try:
        # Fast extraction of header fields with direct slicing
        seq_num, ack_num, flags = struct.unpack("!IIB", packet[:9])
        payload = packet[25:]  # Skip checksum verification
        return seq_num, ack_num, flags, payload
    except Exception as e:
        logger.debug(f"Fast packet parsing failed: {e}")
        return None

def create_packet_fast(seq_num, ack_num, flags, payload=b''):
    """Creates a packet faster by skipping checksum for ACKs and control packets"""
    try:
        if not payload:  # For control packets
            header = struct.pack("!IIB", seq_num, ack_num, flags)
            # Use a simplified checksum for control packets
            checksum = hashlib.md5(header).digest()[:8] + b'\x00' * 8
            return header + checksum
        else:
            # Use normal packet creation for data packets
            return create_packet(seq_num, ack_num, flags, payload)
    except Exception as e:
        logger.error(f"Error creating fast packet: {e}")
        # Fall back to regular packet creation
        return create_packet(seq_num, ack_num, flags, payload)