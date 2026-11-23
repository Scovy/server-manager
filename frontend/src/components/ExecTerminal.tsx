import { useEffect, useRef } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';
import { openAdminSocket } from '../api/authApi';

interface ExecTerminalProps {
  containerId: string;
}

export default function ExecTerminal({ containerId }: ExecTerminalProps) {
  const terminalRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!terminalRef.current || !containerId) return;

    const term = new Terminal({
      cursorBlink: true,
      convertEol: true,
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 13,
      theme: {
        background: '#0b0f17',
        foreground: '#e2e8f0',
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(terminalRef.current);
    fit.fit();

    const controller = new AbortController();
    let ws: WebSocket | undefined;
    const path = `/api/containers/${encodeURIComponent(containerId)}/exec`;
    void openAdminSocket(path, controller.signal).then((socket) => {
      if (controller.signal.aborted) {
        socket.close();
        return;
      }
      ws = socket;
      socket.onopen = () => term.writeln('Connected to container exec session.');
      socket.onmessage = (event) => term.write(String(event.data));
      socket.onerror = () => term.writeln('\r\n[terminal error]');
      socket.onclose = () => term.writeln('\r\n[session closed]');
    }).catch(() => {
      if (!controller.signal.aborted) term.writeln('Could not open an authenticated terminal.');
    });

    const disposable = term.onData((data: string) => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(data);
      }
    });

    const onResize = () => fit.fit();
    window.addEventListener('resize', onResize);

    return () => {
      window.removeEventListener('resize', onResize);
      disposable.dispose();
      controller.abort();
      if (ws) {
        ws.onclose = ws.onerror = ws.onmessage = ws.onopen = null;
        ws.close();
      }
      term.dispose();
    };
  }, [containerId]);

  return <div className="exec-terminal" ref={terminalRef} />;
}
