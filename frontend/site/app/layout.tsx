import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  metadataBase: new URL('http://localhost:3000'),
  icons: { icon: '/favicon.svg' },
  title: '有界｜制造供应链异常闭环演示',
  description: '用一个 217 台汽车订单案例，六步看懂有界 Agent 如何研判、求解、人审、回流和失效重算。',
  openGraph: {
    title: '有界｜制造供应链异常闭环',
    description: '从 217 台订单受影响，到人审、ERP/MES 回流和失效重算。',
    images: [{ url: '/og.png', width: 1200, height: 630, alt: '有界制造供应链异常闭环演示' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: '有界｜制造供应链异常闭环',
    description: '从异常识别到人工批准、系统回流和失效重算。',
    images: ['/og.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
