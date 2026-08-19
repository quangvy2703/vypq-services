// Gói `server-only` cố tình NÉM khi bị import ngoài môi trường react-server —
// đó chính là tác dụng của nó trong bundle. Vitest không có điều kiện đó, nên
// alias sang file rỗng này để test vẫn import được lib/env, lib/gateway.
export {};
