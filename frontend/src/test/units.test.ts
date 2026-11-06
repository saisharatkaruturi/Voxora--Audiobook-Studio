import { describe, expect, it } from "vitest";
import { bookFraction, formatBytes, formatClock, formatDuration } from "@/utils/format";
import { validateFile } from "@/services/upload";
import { pageTitle } from "@/config/brand";

describe("format", () => {
  it("formats clock times", () => {
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(65)).toBe("1:05");
    expect(formatClock(3725)).toBe("1:02:05");
    expect(formatClock(NaN)).toBe("0:00");
  });
  it("formats durations and sizes", () => {
    expect(formatDuration(40)).toBe("40 sec");
    expect(formatDuration(300)).toBe("5 min");
    expect(formatDuration(3725)).toBe("1h 2m");
    expect(formatBytes(1536)).toBe("1.5 KB");
  });
  it("computes listening fraction safely", () => {
    expect(bookFraction(50, 100)).toBe(0.5);
    expect(bookFraction(150, 100)).toBe(1);
    expect(bookFraction(10, null)).toBe(0);
  });
});

describe("upload validation", () => {
  const file = (name: string, size = 10) => new File([new Uint8Array(size)], name);
  it("accepts books and page images", () => {
    for (const n of ["a.pdf", "b.EPUB", "c.docx", "d.txt", "scan.jpg", "p.png"]) expect(validateFile(file(n), 10)).toBeNull();
  });
  it("rejects unsupported, empty and oversized files", () => {
    expect(validateFile(file("virus.exe"), 10)).toMatch(/supported/);
    expect(validateFile(file("empty.pdf", 0), 10)).toMatch(/empty/);
    expect(validateFile(file("huge.pdf", 2 * 1024 * 1024), 1)).toMatch(/limit/);
  });
});

describe("brand", () => {
  it("formats page titles consistently", () => {
    expect(pageTitle("Library")).toBe("VOXORA · Library");
    expect(pageTitle()).toBe("VOXORA — Where stories find their voice.");
  });
});
