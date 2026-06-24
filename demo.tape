# VHS tape — records assets/demo.gif (the README hermetic-demo showcase).
# Build: `vhs demo.tape` from the repo root (needs vhs + ttyd + ffmpeg + glow).
# Warm "Anthropic paper" theme to match assets/banner.svg.

Output assets/demo.gif

Set Shell "zsh"
Set FontSize 22
Set Width 1280
Set Height 800
Set Padding 30
Set Margin 28
Set MarginFill "#f0eee6"
Set BorderRadius 10
Set WindowBar Colorful
Set TypingSpeed 55ms
Set Theme { "name": "AnthropicPaper", "background": "#faf9f5", "foreground": "#141413", "cursor": "#d97757", "selection": "#e8e6dc", "black": "#141413", "red": "#bf4d43", "green": "#5c8a4a", "yellow": "#9a6b1f", "blue": "#4a7396", "magenta": "#8a5a83", "cyan": "#2f7d7d", "white": "#57564f", "brightBlack": "#87867f", "brightRed": "#bf4d43", "brightGreen": "#5c8a4a", "brightYellow": "#9a6b1f", "brightBlue": "#4a7396", "brightMagenta": "#8a5a83", "brightCyan": "#2f7d7d", "brightWhite": "#141413" }

Hide
Type "clear"
Enter
Show

Sleep 700ms
Type "# full pipeline on fixtures — no API keys, no network"
Sleep 400ms
Enter
Type "LOG_LEVEL=error make demo"
Sleep 500ms
Enter
Sleep 5s

Type "sed -n '1,18p' output/report-2026-04.md | glow -s light -w 82 -"
Sleep 400ms
Enter
Sleep 5s
