<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Curator</title>
</head>
<body>
  <main>
    <h1>Curator</h1>

    <section id="what">
      <h2>What</h2>
      <p>
        Curator is a local-first coding-agent workbench. It records accepted user goals,
        compiles them into auditable workflow sessions, dispatches real provider CLIs
        such as Claude Code or Codex, runs deterministic verification, captures evidence,
        and pauses for user input when provider setup, verification, scope, permissions,
        or workspace state need a human decision.
      </p>
      <p>
        The current runtime no longer has a synthetic provider fallback. Tests use local
        fake providers, but the CLI, REPL, scheduler, provider setup, and diagnostics
        require real configured providers for user work.
      </p>
    </section>

    <section id="how">
      <h2>How</h2>
      <h3>Run locally</h3>
      <pre><code>cd /path/to/curator
source .venv/bin/activate
curator</code></pre>

      <h3>Initialize and connect providers</h3>
      <pre><code>curator init --yes
curator provider add claude-code
curator provider add codex
curator provider list</code></pre>
      <p>
        Inside the shell, use <code>/provider add claude-code</code> or
        <code>/provider add codex</code>, then bind role slots with
        <code>/agent bind writer.default &lt;profile&gt;</code> and
        <code>/agent bind reviewer.default &lt;profile&gt;</code>.
      </p>

      <h3>Runtime flow</h3>
      <ol>
        <li>User text becomes a durable goal draft and accepted goal revision.</li>
        <li>The app creates a single-writer workflow session.</li>
        <li>The writer provider receives a context package rendered into the CLI prompt.</li>
        <li>Curator blocks dirty git workspaces before writer dispatch to avoid misattribution.</li>
        <li>The verifier runs discovered or explicit verification commands.</li>
        <li>A fresh-context reviewer provider reviews implementation and verification evidence.</li>
        <li>A human confirmation gate pauses before marking delivery done.</li>
      </ol>

      <h3>Verification</h3>
      <pre><code>source .venv/bin/activate
pytest -p no:cacheprovider -q
ruff check src tests</code></pre>
    </section>

    <section id="why">
      <h2>Why</h2>
      <p>
        Curator keeps providers out of scheduler control flow. Providers produce typed
        output, provider responses, workspace evidence, and streamed events; the scheduler
        owns retry, pause, stop, and resume decisions. This makes provider failures,
        permission problems, missing verification commands, and scope-change requests
        inspectable instead of hidden inside a chat transcript.
      </p>
      <p>
        Real provider setup is explicit because a fallback provider creates misleading
        confidence. A missing or broken CLI now blocks setup, and a goal run without a
        configured provider pauses with next-step guidance instead of producing synthetic
        success.
      </p>
    </section>

    <section id="future">
      <h2>Future improvements/considerations/trade-offs</h2>
      <ul>
        <li>Add an explicit development-only simulator outside production CLI paths if demos are needed.</li>
        <li>Parse structured provider-reported verification commands from final provider output.</li>
        <li>Add an opt-in dirty-workspace mode with stronger diff partitioning.</li>
        <li>Track provider health and quota over time for better slot routing.</li>
        <li>Expand reviewer evidence beyond summaries while preserving fresh-context isolation.</li>
      </ul>
    </section>
  </main>
</body>
</html>
