#!/usr/bin/env node
/*
 * `npm run dev` from the repository root: the API and the SPA dev server in one
 * terminal, in the right directories, so nobody has to remember that the
 * frontend lives one level down and that Vite proxies /api/v1 to port 8000.
 *
 * No process-runner dependency: two children, prefixed output, and a shutdown
 * that takes both down. On Windows a child cannot be killed with a signal —
 * uvicorn's reloader and Vite both spawn grandchildren — so the whole tree is
 * terminated with taskkill rather than leaving an orphan holding the port.
 */
import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const isWindows = process.platform === 'win32'
const API_PORT = process.env.PORT ?? '8000'

const venvPython = join(root, '.venv', isWindows ? 'Scripts/python.exe' : 'bin/python')
const python = existsSync(venvPython) ? venvPython : 'python'
const viteBin = join(root, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js')

if (!existsSync(viteBin)) {
  console.error('frontend/node_modules is missing. Run: npm install --prefix frontend')
  process.exit(1)
}

// Watchfiles is not a declared dependency, so --reload is only passed when the
// interpreter can actually import it. The fallback poller would watch the whole
// repository including .venv, which is worse than no reload.
const hasWatchfiles =
  spawnSync(python, ['-c', 'import watchfiles'], { stdio: 'ignore' }).status === 0

const apiArgs = ['-m', 'uvicorn', 'api.app:app', '--host', '127.0.0.1', '--port', API_PORT]
if (hasWatchfiles) apiArgs.push('--reload')

const children = []
let shuttingDown = false
let exitCode = 0

function prefixOutput(label, color, stream) {
  let buffer = ''
  stream.setEncoding('utf8')
  stream.on('data', (chunk) => {
    buffer += chunk
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      process.stdout.write(line ? `${color}${label}\x1b[0m ${line}\n` : '\n')
    }
  })
  stream.on('end', () => {
    if (buffer) process.stdout.write(`${color}${label}\x1b[0m ${buffer}\n`)
  })
}

function killTree(child) {
  if (child.exitCode !== null || child.killed) return
  if (isWindows) {
    spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
    return
  }
  try {
    process.kill(-child.pid, 'SIGTERM')
  } catch {
    child.kill('SIGTERM')
  }
}

function shutdown(code) {
  if (shuttingDown) return
  shuttingDown = true
  exitCode = code
  for (const child of children) killTree(child)
  // Windows has no signal to wait for; give the tree a moment, then leave.
  setTimeout(() => process.exit(exitCode), 600).unref()
}

function start(label, color, command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: root,
    stdio: ['ignore', 'pipe', 'pipe'],
    // A process group on POSIX (so the tree can be signalled) and detached on
    // Windows only to keep the console clean; the tree is killed by pid there.
    detached: !isWindows,
    ...options,
  })

  children.push(child)
  prefixOutput(label, color, child.stdout)
  prefixOutput(label, color, child.stderr)

  child.on('error', (error) => {
    console.error(`${color}${label}\x1b[0m failed to start: ${error.message}`)
    shutdown(1)
  })

  child.on('exit', (code, signal) => {
    if (shuttingDown) return
    const reason = signal ? `signal ${signal}` : `code ${code ?? 0}`
    console.error(`${color}${label}\x1b[0m exited (${reason}); stopping the other process`)
    shutdown(code ?? 1)
  })

  return child
}

async function waitForApi(child, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (child.exitCode !== null || shuttingDown) return false
    try {
      const response = await fetch(`http://127.0.0.1:${API_PORT}/health`, {
        signal: AbortSignal.timeout(1500),
      })
      // 503 means the API answered but its database is down. Starting the SPA
      // anyway would show a network error that blames the wrong service.
      if (response.ok) return true
    } catch {
      // not listening yet
    }
    await new Promise((done) => setTimeout(done, 400))
  }
  return false
}

// The API logs arrows and em dashes; a Windows console at cp1252 turns those
// into replacement characters unless the child is told otherwise.
const api = start('api', '\x1b[36m', python, apiArgs, {
  env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
})

console.log(`\nwaiting for the API on http://127.0.0.1:${API_PORT} ...`)
if (!(await waitForApi(api))) {
  if (!shuttingDown) {
    console.error(
      `\nThe API did not become healthy on port ${API_PORT}. ` +
        'Check DATABASE_URL in .env, then run this again.',
    )
  }
  shutdown(1)
} else {
  console.log(`api  http://127.0.0.1:${API_PORT}/health  ready`)
  start('web', '\x1b[35m', process.execPath, [viteBin], { cwd: join(root, 'frontend') })
  console.log('web  http://localhost:3000\n')
}

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(signal, () => shutdown(0))
}
