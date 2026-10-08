import axios from 'axios';
import { LARK_AUTH_BASE } from './config';

export interface FeishuUser {
  user_id: string;
  name: string;
  department: string;
  role: string;
}

// 登录态走 httpOnly Cookie，同源下自动携带
const client = axios.create({
  baseURL: LARK_AUTH_BASE,
  timeout: 15000,
  withCredentials: true,
});

export const authApi = {
  /** 获取飞书授权链接（后端同时写入一次性 state Cookie） */
  async getAuthorizeUrl(): Promise<string> {
    const { data } = await client.get('/authorize-url');
    return data.authorize_url as string;
  },

  /** 用授权 code 换取登录态 */
  async exchange(code: string, state: string): Promise<FeishuUser> {
    const { data } = await client.post('/exchange', { code, state });
    return data.user as FeishuUser;
  },

  /** 获取当前登录用户（未登录返回 401） */
  async me(): Promise<FeishuUser> {
    const { data } = await client.get('/me');
    return data.user as FeishuUser;
  },

  async logout(): Promise<void> {
    await client.post('/logout');
  },

  /** 整页跳转到飞书授权页 */
  async redirectToFeishu(): Promise<void> {
    window.location.href = await authApi.getAuthorizeUrl();
  },
};

export default authApi;