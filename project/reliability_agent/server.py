"""Small local HTTP service; inference needs only artifacts, no source CSVs."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path


def make_server(agent, host='127.0.0.1', port=8765):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def reply(self, code, result):
            body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/health':
                self.reply(200, {'status':'ready','model_version':agent.artifact['version']})
            elif self.path == '/schema':
                self.reply(200, json.loads(Path(__file__).with_name('schema.json').read_text(encoding='utf-8')))
            else:
                self.reply(404, {'error':'not_found'})

        def do_POST(self):
            if self.path not in ['/assess', '/compare']:
                self.reply(404, {'error':'not_found'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1048576:
                    self.reply(413, {'error':'request_body_must_be_1_to_1048576_bytes'})
                    return
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or 'state' not in body:
                    raise ValueError('Request requires state object')
                if self.path == '/compare':
                    if body.get('candidate') is None:
                        raise ValueError('/compare requires candidate')
                    result = agent.compare(body['state'], body['candidate'])
                else:
                    result = agent.assess(body['state'], body.get('candidate'))
                self.reply(200, result)
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                self.reply(400, {'error':'invalid_request','message':str(exc)})

    return ThreadingHTTPServer((host, port), Handler)


def serve(agent, host, port):
    server = make_server(agent, host, port)
    print(f'ReliabilityAgent: http://{host}:{server.server_address[1]}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
