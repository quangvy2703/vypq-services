FROM node:24-alpine AS deps
WORKDIR /app
RUN corepack enable
# pnpm-workspace.yaml phải đi kèm: nó giữ allowBuilds (esbuild, sharp) — thiếu
# file này pnpm coi như chưa duyệt script build nào và dừng cài đặt giữa chừng.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:24-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Build không cần bí mật thật: mọi biến đều đọc lúc chạy (getServerEnv), không
# nhúng vào bundle. Đặt giá trị giả để next build không chạm phải nhánh ném lỗi.
ENV GATEWAY_TOKEN=build DASHBOARD_PASSWORD=build SESSION_SECRET=build
RUN pnpm build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production PORT=3001 HOSTNAME=0.0.0.0
# Không chạy bằng root: dashboard nhận file upload từ người dùng.
RUN addgroup -S vypq && adduser -S vypq -G vypq
COPY --from=builder --chown=vypq:vypq /app/.next/standalone ./
COPY --from=builder --chown=vypq:vypq /app/.next/static ./.next/static
USER vypq
EXPOSE 3001
CMD ["node", "server.js"]
