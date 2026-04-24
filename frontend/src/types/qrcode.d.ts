declare module 'qrcode' {
  interface ToDataUrlOptions {
    errorCorrectionLevel?: 'L' | 'M' | 'Q' | 'H';
    margin?: number;
    width?: number;
    color?: {
      dark?: string;
      light?: string;
    };
  }

  interface QRCodeModule {
    toDataURL(text: string, options?: ToDataUrlOptions): Promise<string>;
  }

  const QRCode: QRCodeModule;
  export default QRCode;
}
