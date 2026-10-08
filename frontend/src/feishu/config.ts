/**
 * 飞书模式开关
 *
 * VITE_LARK_ENABLED=true 时启用飞书免登入口，否则走原网页版（DeptSelector）流程。
 * 默认未设置 = false，原网页版完全不受影响。
 */
export const FEISHU_ENABLED =
  (import.meta as any).env?.VITE_LARK_ENABLED === 'true';

/** 飞书免登接口前缀 */
export const LARK_AUTH_BASE = '/api/auth/lark';

/** 飞书回跳路径，需与后端 LARK_REDIRECT_URI 的 path 一致 */
export const LARK_CALLBACK_PATH = '/auth/callback';

/**
 * 可见性部门：飞书暂无部门，统一按「全员」可见。
 * 后端守卫中间件会依据登录令牌覆盖该值，前端无法伪造越权。
 */
export const VISIBILITY_DEPT = '全员';