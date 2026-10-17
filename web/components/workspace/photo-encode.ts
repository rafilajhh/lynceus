/**
 * Load-photo encoding for the vision model. Image tokens, and so VLM
 * latency, grow with pixel count; a 12 MP phone photo has ~10x the pixels of
 * a 1280x960 one. 1280 is still >2x the 524 px image the Token Factory probe
 * localised at IoU >= 0.888 (docs/research/token-factory-probe.md).
 */

import { blobToBase64 } from "@/lib/inspect-api";

const MAX_PHOTO_EDGE_PX = 1280;
const PHOTO_JPEG_QUALITY = 0.85;

/** The photo re-encoded as a JPEG with its long edge at MAX_PHOTO_EDGE_PX,
 * or null when it is already that small or the browser cannot decode or
 * re-encode it (the original bytes are sent instead). Aspect ratio is kept,
 * so normalised (0..1) boxes map onto either image; the canvas applies EXIF
 * orientation, so the model sees what the preview shows. */
async function downscaledJpeg(file: File): Promise<Blob | null> {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const longEdge = Math.max(img.naturalWidth, img.naturalHeight);
    if (longEdge <= MAX_PHOTO_EDGE_PX) return null;
    const scale = MAX_PHOTO_EDGE_PX / longEdge;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    // A transparent PNG would turn black in a JPEG; flatten onto white.
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", PHOTO_JPEG_QUALITY),
    );
  } catch {
    return null;
  } finally {
    URL.revokeObjectURL(url);
  }
}

export interface EncodedPhoto {
  base64: string;
  mime: string;
  /** The filename the audit stores: only re-encoded bytes become a .jpg. */
  filename: string;
}

/** A load photo as sent to the vision model (downscaled when large). */
export async function encodeLoadPhoto(file: File): Promise<EncodedPhoto> {
  const small = await downscaledJpeg(file);
  if (!small) return { base64: await blobToBase64(file), mime: file.type, filename: file.name };
  const filename = /\.jpe?g$/i.test(file.name)
    ? file.name
    : `${file.name.replace(/\.[^./\\]+$/, "")}.jpg`;
  return { base64: await blobToBase64(small), mime: "image/jpeg", filename };
}

/** A document photo, bytes unchanged (the reader may recognise them). */
export async function encodeRaw(file: File): Promise<EncodedPhoto> {
  return { base64: await blobToBase64(file), mime: file.type, filename: file.name };
}

/** data: URL of encoded bytes: survives a later object-URL revoke. */
export function dataUrl(photo: EncodedPhoto): string {
  return `data:${photo.mime || "image/jpeg"};base64,${photo.base64}`;
}
