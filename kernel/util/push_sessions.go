package util

import "sync"

// 保护 Add/RemovePushChan 中完整的内外层 session 表更新。
var pushSessionsMu sync.Mutex
