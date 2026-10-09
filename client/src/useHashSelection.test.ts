import { describe, expect, it } from "vitest";
import { parseHash } from "./useHashSelection";

describe("parseHash", () => {
  it("returns no selection for an empty or unrelated hash", () => {
    expect(parseHash("")).toEqual({ kind: "none" });
    expect(parseHash("#/other/abc")).toEqual({ kind: "none" });
    expect(parseHash("#/c/")).toEqual({ kind: "none" });
  });

  it("decodes a valid selection, including percent-encoded characters", () => {
    expect(parseHash("#/c/abc-123")).toEqual({ kind: "id", id: "abc-123" });
    expect(parseHash("#/c/a%2Fb%20c")).toEqual({ kind: "id", id: "a/b c" });
  });

  it("does not throw on malformed percent-encoding or invalid UTF-8", () => {
    for (const bad of ["#/c/%", "#/c/%E0%A4%A", "#/c/%FF", "#/c/%C0%AF", "#/c/abc%", "#/c/%zz"]) {
      expect(() => parseHash(bad)).not.toThrow();
      expect(parseHash(bad)).toEqual({ kind: "invalid" });
    }
  });

  it("leaves an id that merely looks odd to the server to reject", () => {
    // The identifier format is the server's concern (it answers 400 invalid_identifier).
    expect(parseHash("#/c/not-a-uuid")).toEqual({ kind: "id", id: "not-a-uuid" });
  });
});
