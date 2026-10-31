"""
Mini TCP over UDP  (Computer Networks project)
Features: 3-way handshake, seq/ack numbers, checksum, timeout + retransmission,
stop-and-wait reliability, simulated packet loss, FIN teardown.

Run:
  python mini_tcp.py demo [loss]      # server + client in one process (default loss 0.3)
  python mini_tcp.py server [loss]    # terminal 1
  python mini_tcp.py client [loss]    # terminal 2
"""
import socket, struct, sys, time, random, threading, zlib

SYN, ACK, FIN, DATA = 1, 2, 4, 8
HDR = struct.Struct("!IIBHI")      # seq, ack, flags, length, checksum
MSS = 50                           # max payload bytes per segment
RTO = 0.3                          # retransmission timeout (seconds)
MAX_TRIES = 30
ADDR = ("127.0.0.1", 9999)
stats = {"sent": 0, "dropped": 0, "retx": 0}


def flag_str(f):
    return "|".join(n for b, n in ((SYN, "SYN"), (ACK, "ACK"), (FIN, "FIN"), (DATA, "DATA")) if f & b)


def pack(seq, ack, flags, payload=b""):
    h0 = HDR.pack(seq, ack, flags, len(payload), 0)
    return HDR.pack(seq, ack, flags, len(payload), zlib.crc32(h0 + payload)) + payload


def unpack(raw):
    if len(raw) < HDR.size:
        return None
    seq, ack, flags, ln, csum = HDR.unpack(raw[:HDR.size])
    payload = raw[HDR.size:HDR.size + ln]
    if zlib.crc32(HDR.pack(seq, ack, flags, ln, 0) + payload) != csum:
        return None                # corrupted -> ignore
    return seq, ack, flags, payload


def lossy_send(sock, addr, pkt, loss, who):
    seq, ack, flags, payload = unpack(pkt)
    stats["sent"] += 1
    if random.random() < loss:
        stats["dropped"] += 1
        print(f"[{who}] x DROPPED  seq={seq} ack={ack} {flag_str(flags)}")
        return
    print(f"[{who}] -> seq={seq} ack={ack} {flag_str(flags)} len={len(payload)}")
    sock.sendto(pkt, addr)


def recv(sock, timeout):
    sock.settimeout(timeout)
    try:
        raw, addr = sock.recvfrom(2048)
    except socket.timeout:
        return None, None
    p = unpack(raw)
    return (p, addr) if p else (None, None)


def server(loss, received, ready=None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(ADDR)
    if ready:
        ready.set()
    isn = random.randint(0, 1000)
    state, expected, peer = "LISTEN", 0, None
    while True:
        p, addr = recv(s, 1.0 if state == "CLOSING" else RTO)
        if p is None:
            if state == "CLOSING":
                break
            if state == "SYN_RCVD":    # resend SYN-ACK
                lossy_send(s, peer, pack(isn, expected, SYN | ACK), loss, "SERVER")
            continue
        seq, ack, flags, payload = p
        if flags & SYN:
            peer, expected, state = addr, seq + 1, "SYN_RCVD"
            lossy_send(s, peer, pack(isn, expected, SYN | ACK), loss, "SERVER")
        elif flags & FIN:
            expected = seq + 1
            state = "CLOSING"
            lossy_send(s, addr, pack(isn + 1, expected, FIN | ACK), loss, "SERVER")
        elif flags & DATA and state in ("SYN_RCVD", "ESTABLISHED"):
            state = "ESTABLISHED"      # data implies final handshake ACK arrived
            if seq == expected:
                received.append(payload)
                expected += len(payload)
            lossy_send(s, addr, pack(isn + 1, expected, ACK), loss, "SERVER")  # dup-ACK if out of order
        elif flags & ACK and state == "SYN_RCVD":
            state = "ESTABLISHED"
    s.close()


def client(loss, message):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    isn = random.randint(0, 1000)

    def reliable(pkt, want_ack, need_flags=0):
        """send pkt until an ACK >= want_ack (with need_flags) arrives"""
        for i in range(MAX_TRIES):
            if i:
                stats["retx"] += 1
                print("[CLIENT] ! timeout -> retransmit")
            lossy_send(s, ADDR, pkt, loss, "CLIENT")
            end = time.time() + RTO
            while time.time() < end:
                p, _ = recv(s, max(0.01, end - time.time()))
                if p and p[2] & ACK and p[1] >= want_ack and (p[2] & need_flags) == need_flags:
                    return p
        raise RuntimeError("connection failed: too many retries")

    # 3-way handshake
    print("--- HANDSHAKE ---")
    synack = reliable(pack(isn, 0, SYN), isn + 1, SYN)
    seq = isn + 1
    lossy_send(s, ADDR, pack(seq, synack[0] + 1, ACK), loss, "CLIENT")

    # data transfer (stop-and-wait)
    print("--- DATA ---")
    for off in range(0, len(message), MSS):
        chunk = message[off:off + MSS]
        reliable(pack(seq, 0, DATA, chunk), seq + len(chunk))
        seq += len(chunk)

    # teardown
    print("--- TEARDOWN ---")
    reliable(pack(seq, 0, FIN), seq + 1, FIN)
    lossy_send(s, ADDR, pack(seq + 1, 0, ACK), loss, "CLIENT")
    s.close()


def demo(loss):
    msg = (b"Mini TCP demo: reliable delivery over unreliable UDP. " * 8)
    received, ready = [], threading.Event()
    t = threading.Thread(target=server, args=(loss, received, ready))
    t.start()
    ready.wait()
    t0 = time.time()
    client(loss, msg)
    t.join()
    got = b"".join(received)
    print("\n=== RESULT ===")
    print(f"loss rate        : {loss:.0%}")
    print(f"bytes sent/recv  : {len(msg)} / {len(got)}")
    print(f"data intact      : {got == msg}")
    print(f"packets sent     : {stats['sent']}  (dropped {stats['dropped']}, retransmissions {stats['retx']})")
    print(f"time             : {time.time() - t0:.2f}s")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"
    loss = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
    if mode == "demo":
        demo(loss)
    elif mode == "server":
        buf = []
        server(loss, buf)
        print("Received:", b"".join(buf).decode(errors="replace"))
    elif mode == "client":
        client(loss, b"Hello from Mini TCP client! " * 5)