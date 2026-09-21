import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16은 dev 리소스에 대한 cross-origin 요청을 기본 차단한다. dev 서버는
  // localhost에 바인딩되므로 127.0.0.1로 접속하면 클라이언트 청크가 막혀
  // 하이드레이션이 조용히 실패한다(화면이 로딩 상태에서 멈춘다).
  // 개발자가 어느 쪽으로 접속하든 동작하도록 둘 다 허용한다.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
