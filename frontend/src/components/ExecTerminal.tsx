import { useEffect, useRef } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';

interface ExecTerminalProps {
  containerId: string;
}

function buildWsUrl(containerId: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/api/containers/${containerId}/exec?cmd=/bin/sh`;
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

    const ws = new WebSocket(buildWsUrl(containerId));

    ws.onopen = () => {
      term.writeln('Connected to container exec session.');
      term.write('\r\n');
    };

    ws.onmessage = (event) => {
      term.write(String(event.data));
    };

    ws.onerror = () => {
      term.writeln('\r\n[terminal error]');
    };

    ws.onclose = () => {
      term.writeln('\r\n[session closed]');
    };

    const disposable = term.onData((data: string) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data);
      }
    });

    const onResize = () => fit.fit();
    window.addEventListener('resize', onResize);

    return () => {
      window.removeEventListener('resize', onResize);
      disposable.dispose();
      ws.close();
      term.dispose();
    };
  }, [containerId]);

  return <div className="exec-terminal" ref={terminalRef} />;
}
