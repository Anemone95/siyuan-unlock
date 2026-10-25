#!/usr/bin/env bash
# 把个人提交 rebase 到思源正式版 tag，并把 iOS 壳的个人提交 rebase 到上游 main。
# 两个仓库都成功后才推送；有冲突时开 Issue 列出冲突文件，由维护者在本地解决。
set -euo pipefail

tag=${1:?Usage: personal-sync.sh <official tag> <siyuan checkout> <siyuan-ios checkout>}
siyuan=${2:?}
ios=${3:?}
conflicts=

# rebase <checkout> <upstream ref>：在当前分支上重放个人提交。
rebase() {
  git -C "$1" config user.name 'github-actions[bot]'
  git -C "$1" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
  if ! git -C "$1" rebase --quiet "$2"; then
    conflicts+="**$1** onto \`$2\`:"$'\n'"$(git -C "$1" diff --name-only --diff-filter=U | sed 's/^/- /')"$'\n\n'
    git -C "$1" rebase --abort
  fi
}

git -C "$siyuan" fetch --quiet --no-tags https://github.com/siyuan-note/siyuan.git "refs/tags/$tag:refs/tags/$tag"
git -C "$ios" fetch --quiet --no-tags https://github.com/siyuan-note/siyuan-ios.git main:refs/remotes/upstream/main
siyuan_head=$(git -C "$siyuan" rev-parse HEAD)
ios_head=$(git -C "$ios" rev-parse HEAD)
rebase "$siyuan" "$tag"
rebase "$ios" upstream/main

if [ -n "$conflicts" ]; then
  gh issue create --repo Anemone95/siyuan-unlock --title "Rebase onto $tag" --body "$(cat <<EOF
Rebasing our commits onto the official release $tag stopped with conflicts:

$conflicts
Resolve them locally as described in [docs/personal-release.md](https://github.com/Anemone95/siyuan-unlock/blob/master/docs/personal-release.md#本地解决冲突), push siyuan-ios \`main\` first and then \`master\` with \`$tag\`, and close this issue.
EOF
)"
  exit 1
fi

test "$(jq -r .version "$siyuan/app/package.json")" = "${tag#v}"
git -C "$ios" push --force-with-lease="main:$ios_head" origin HEAD:main
git -C "$siyuan" push --atomic --force-with-lease="master:$siyuan_head" origin HEAD:master "refs/tags/$tag"
echo "Rebased master onto $tag and siyuan-ios main onto upstream main"
