#!/usr/bin/env python3
"""
Cross-platform USB UART Terminal
Works on Linux, Windows, and macOS.
Requires: pip install pyserial
"""

import serial
import serial.tools.list_ports
import threading
import sys
import time
import os

# ── ANSI color codes (disabled automatically on Windows if not supported) ──
def supports_color():
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

USE_COLOR = supports_color()

def c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

CYAN   = lambda t: c("96", t)
GREEN  = lambda t: c("92", t)
YELLOW = lambda t: c("93", t)
RED    = lambda t: c("91", t)
DIM    = lambda t: c("2",  t)
BOLD   = lambda t: c("1",  t)


# ── Port discovery ─────────────────────────────────────────────────────────
def list_ports():
    ports = serial.tools.list_ports.comports()
    return sorted(ports, key=lambda p: p.device)


def pick_port():
    ports = list_ports()
    if not ports:
        print(RED("No serial ports found. Make sure your device is plugged in."))
        sys.exit(1)

    print(BOLD("\nAvailable serial ports:"))
    for i, p in enumerate(ports):
        desc = f" — {p.description}" if p.description != "n/a" else ""
        print(f"  {CYAN(str(i))}  {p.device}{DIM(desc)}")

    if len(ports) == 1:
        choice = 0
        print(f"\nAuto-selected: {GREEN(ports[0].device)}")
    else:
        while True:
            try:
                raw = input(f"\nSelect port [{CYAN('0')}–{CYAN(str(len(ports)-1))}]: ").strip()
                choice = int(raw)
                if 0 <= choice < len(ports):
                    break
            except (ValueError, KeyboardInterrupt):
                pass
            print(RED("Invalid selection, try again."))

    return ports[choice].device


BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]

def pick_baud():
    print(BOLD("\nCommon baud rates:"))
    for i, b in enumerate(BAUD_RATES):
        print(f"  {CYAN(str(i))}  {b}")
    print(f"  {CYAN('c')}  Custom")

    while True:
        raw = input(f"\nSelect baud rate [{CYAN('0')}–{CYAN(str(len(BAUD_RATES)-1))} or c]: ").strip().lower()
        if raw == "c":
            try:
                baud = int(input("Enter baud rate: ").strip())
                return baud
            except ValueError:
                print(RED("Invalid baud rate."))
        else:
            try:
                idx = int(raw)
                if 0 <= idx < len(BAUD_RATES):
                    return BAUD_RATES[idx]
            except ValueError:
                pass
        print(RED("Invalid selection, try again."))


# ── Reader thread ──────────────────────────────────────────────────────────
stop_event = threading.Event()

def reader_thread(ser):
    """Continuously read from UART and print to stdout."""
    buf = b""
    while not stop_event.is_set():
        try:
            if ser.in_waiting:
                chunk = ser.read(ser.in_waiting)
                buf += chunk
                # Print complete lines; keep partial line in buffer
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    decoded = line.rstrip(b"\r").decode("utf-8", errors="replace")
                    print(f"\r{GREEN('<<')} {decoded}")
                    # Reprint the prompt hint so it stays visible
                    print(f"{CYAN('>>')} ", end="", flush=True)
            else:
                time.sleep(0.01)
        except serial.SerialException:
            if not stop_event.is_set():
                print(RED("\n[Connection lost]"))
                stop_event.set()
            break
        except Exception as e:
            if not stop_event.is_set():
                print(RED(f"\n[Reader error: {e}]"))
            break


# ── Line ending helper ─────────────────────────────────────────────────────
LINE_ENDINGS = {
    "cr":   b"\r",
    "lf":   b"\n",
    "crlf": b"\r\n",
    "none": b"",
}

def pick_line_ending():
    opts = list(LINE_ENDINGS.keys())
    print(BOLD("\nLine ending to send:"))
    for i, name in enumerate(opts):
        print(f"  {CYAN(str(i))}  {name.upper()}")
    default = 2  # CRLF
    while True:
        raw = input(f"\nSelect [{CYAN('0')}–{CYAN(str(len(opts)-1))}] (default {CYAN(str(default))}=CRLF): ").strip()
        if raw == "":
            return LINE_ENDINGS[opts[default]]
        try:
            idx = int(raw)
            if 0 <= idx < len(opts):
                return LINE_ENDINGS[opts[idx]]
        except ValueError:
            pass
        print(RED("Invalid selection."))


# ── Main terminal loop ─────────────────────────────────────────────────────
def run_terminal(port, baud, line_ending):
    print(f"\n{BOLD('Connecting to')} {CYAN(port)} @ {CYAN(str(baud))} baud …")
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
        )
    except serial.SerialException as e:
        print(RED(f"Failed to open port: {e}"))
        sys.exit(1)

    print(GREEN(f"Connected. Type your commands. Special commands:"))
    print(DIM("  :quit  or  Ctrl-C  — exit"))
    print(DIM("  :ports             — list available ports"))
    print(DIM("  :baud <rate>       — change baud rate on the fly"))
    print(DIM("  :hex               — toggle hex dump mode"))
    print()

    t = threading.Thread(target=reader_thread, args=(ser,), daemon=True)
    t.start()

    hex_mode = False

    try:
        while not stop_event.is_set():
            try:
                line = input(f"{CYAN('>>')} ")
            except EOFError:
                break

            # ── Special commands ──────────────────────────────────────
            if line.strip() == ":quit":
                break
            elif line.strip() == ":ports":
                print(BOLD("Available ports:"))
                for p in list_ports():
                    print(f"  {p.device}  {DIM(p.description)}")
                continue
            elif line.strip().startswith(":baud"):
                parts = line.strip().split()
                if len(parts) == 2:
                    try:
                        new_baud = int(parts[1])
                        ser.baudrate = new_baud
                        print(YELLOW(f"Baud rate changed to {new_baud}"))
                    except ValueError:
                        print(RED("Usage: :baud <rate>"))
                else:
                    print(RED("Usage: :baud <rate>"))
                continue
            elif line.strip() == ":hex":
                hex_mode = not hex_mode
                print(YELLOW(f"Hex dump mode {'ON' if hex_mode else 'OFF'}"))
                continue

            # ── Send data ─────────────────────────────────────────────
            payload = line.encode("utf-8") + line_ending
            try:
                ser.write(payload)
                if hex_mode:
                    print(DIM(f"   sent ({len(payload)} bytes): {payload.hex(' ')}"))
            except serial.SerialException as e:
                print(RED(f"Write error: {e}"))
                break

    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        time.sleep(0.1)
        ser.close()
        print(f"\n{YELLOW('Connection closed.')}")


# ── Entry point ────────────────────────────────────────────────────────────
def main():
    print(BOLD(CYAN("━" * 48)))
    print(BOLD(CYAN("   USB UART Terminal  (Linux / Windows / macOS)")))
    print(BOLD(CYAN("━" * 48)))

    port        = pick_port()
    baud        = pick_baud()
    line_ending = pick_line_ending()

    run_terminal(port, baud, line_ending)


if __name__ == "__main__":
    main()
