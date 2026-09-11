/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    // 前端同源代理到 FastAPI，避免浏览器跨域，并方便 PDF iframe 直接引用
    return [
      { source: '/api/:path*', destination: 'http://127.0.0.1:8000/api/:path*' },
    ];
  },
};
export default nextConfig;
