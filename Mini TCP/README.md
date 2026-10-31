# Mini TCP over UDP

A reliable transport protocol implementation built on top of UDP, featuring TCP-like reliability mechanisms.

## Features

- **3-way handshake** (SYN, SYN-ACK, ACK) for connection establishment
- **Sequence and acknowledgment numbers** for reliable data transfer
- **Checksum validation** using CRC32 for packet integrity
- **Timeout and retransmission** mechanism for handling lost packets
- **Stop-and-wait reliability** for guaranteed delivery
- **Simulated packet loss** for testing robustness
- **Fin tear-down** (FIN, FIN-ACK, ACK) for graceful connection termination

## How It Works

The implementation divides the communication into three phases:

1. **Connection Establishment** - Standard 3-way TCP handshake
2. **Data Transfer** - Stop-and-wait protocol with sequence numbers and acknowledgments
3. **Connection Termination** - Fin-based tear-down sequence

## Usage

Run the program in one of three modes:

### Demo Mode (Recommended)
Runs both server and client in a single process for easy testing:
```bash
python mini_tcp.py demo [loss_rate]
```
- `loss_rate`: Optional packet loss probability (0.0-1.0, default 0.3)

### Server Mode
Terminal 1:
```bash
python mini_tcp.py server [loss_rate]
```

### Client Mode
Terminal 2:
```bash
python mini_tcp.py client [loss_rate]
```

## Technical Details

- **Header Format**: Sequence number (4 bytes), Acknowledgment number (4 bytes), Flags (1 byte), Length (2 bytes), Checksum (2 bytes)
- **Flags**: 
  - SYN (1): Synchronize sequence numbers
  - ACK (2): Acknowledgment field significant
  - FIN (4): No more data from sender
  - DATA (8): Payload data present
- **Maximum Segment Size (MSS)**: 50 bytes
- **Retransmission Timeout (RTO)**: 0.3 seconds
- **Maximum Retries**: 30 attempts

## Packet Loss Simulation

The implementation simulates network unreliability by randomly dropping packets based on the specified loss rate. This allows testing of:
- Retransmission mechanisms
- Connection recovery
- Robustness under adverse network conditions

## Statistics

During execution, the program tracks:
- Packets sent
- Packets dropped (simulated loss)
- Retransmissions due to timeout

## Implementation Notes

- Uses UDP sockets (`socket.SOCK_DGRAM`) for underlying transport
- Implements custom reliability layer on top of unreliable UDP
- Thread-safe design for concurrent server/client operation in demo mode
- Payload data is transmitted as raw bytes (supports any data type)

## Educational Value

This implementation demonstrates core concepts from computer networking:
- Transport layer protocols
- Reliability techniques (acknowledgments, timeouts, retransmissions)
- Connection lifecycle management
- Error detection and correction
- Network simulation and testing

Built as a Computer Networks project to understand TCP internals through hands-on implementation.