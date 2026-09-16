#!/usr/bin/env bash
# Stop 复审提醒：任务结束前检查完成门；始终 exit 0（提醒不阻断）。
cat >&2 <<'EOF'
[review-reminder] 收尾前自查：
1. resolver --check 是否通过（改过路由/规则时）；
2. make ci-check 与针对性测试是否实际运行并通过；
3. 终端证据是否已读回并置 images_reviewed（有 UI/主题渲染时）；
4. 生成物（docs/kb/chunks.json）是否按需再生并审 diff；
5. commit 是否符合 Conventional Commits 且披露 AI 参与。
EOF
exit 0
