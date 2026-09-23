FROM --platform=$BUILDPLATFORM node:22 AS node-build

ARG NPM_REGISTRY=

WORKDIR /app
ADD app/package.json app/pnpm* app/.npmrc .

RUN <<EORUN
#!/bin/bash -e
corepack enable
corepack install --global $(node -e 'console.log(require("./package.json").packageManager)')
npm config set registry ${NPM_REGISTRY}
pnpm install --silent
EORUN

ADD app/ .
RUN <<EORUN
#!/bin/bash -e
pnpm run build
node scripts/trimChangelogs.js
mkdir /artifacts
mv appearance stage guide /artifacts/
if [ -d changelogs ]; then mv changelogs /artifacts/; fi
EORUN

FROM --platform=$BUILDPLATFORM tonistiigi/xx:1.7.0@sha256:010d4b66aed389848b0694f91c7aaee9df59a6f20be7f5d12e53663a37bd14e2 AS xx
FROM --platform=$BUILDPLATFORM golang:1.26-alpine AS go-build
COPY --from=xx / /

RUN <<EORUN
#!/bin/sh -e
apk add --no-cache clang lld
go env -w GO111MODULE=on
go env -w CGO_ENABLED=1
EORUN

WORKDIR /kernel
ADD kernel/go.* .
RUN --mount=type=cache,target=/root/.cache/go-build --mount=type=cache,target=/go/pkg \
    go mod download

ADD kernel/ .
ARG TARGETPLATFORM
RUN xx-apk add --no-cache gcc musl-dev
RUN --mount=type=cache,target=/root/.cache/go-build --mount=type=cache,target=/go/pkg \
    xx-go build -o kernel -tags "fts5 sqlcipher" -ldflags "-s -w" && xx-verify kernel

FROM alpine:latest
LABEL maintainer="Liang Ding<845765@qq.com>"

RUN apk add --no-cache ca-certificates tzdata su-exec

ENV TZ=Asia/Shanghai
ENV HOME=/home/siyuan
ENV RUN_IN_CONTAINER=true
EXPOSE 6806

WORKDIR /opt/siyuan/
COPY --from=go-build --chmod=755 /kernel/kernel /kernel/entrypoint.sh .
COPY --from=node-build /artifacts .
COPY LICENSE THIRD_PARTY_NOTICES.md .

ENTRYPOINT ["/opt/siyuan/entrypoint.sh"]
# 默认启动伺服。若通过 `docker run` / `command:` 传额外参数，需自行带上 `serve` 子命令，
# 否则用户参数会整体覆盖 CMD。
CMD ["/opt/siyuan/kernel", "serve"]
