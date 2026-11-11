import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  Button,
  Input,
  Select,
  Textarea,
  Checkbox,
  Modal,
  Avatar,
  Badge,
  Spinner,
  EmptyState,
  Tabs,
} from "./index";

describe("FE-21 Reusable UI Components", () => {
  describe("Button Component", () => {
    it("renders with variant classes and text", () => {
      const html = renderToStaticMarkup(
        <Button variant="lime">Click Me</Button>,
      );
      expect(html).toContain("Click Me");
      expect(html).toContain("bg-lime");
      expect(html).toContain("text-ink");
    });

    it("displays spinner and aria-busy when isLoading", () => {
      const html = renderToStaticMarkup(<Button isLoading>Submitting</Button>);
      expect(html).toContain('aria-busy="true"');
      expect(html).toContain('role="status"');
    });

    it("respects disabled state", () => {
      const html = renderToStaticMarkup(<Button disabled>Disabled</Button>);
      expect(html).toContain("disabled");
    });
  });

  describe("Form Controls (Accessibility & Labels)", () => {
    it("Input links label, error and helper text via ARIA attributes", () => {
      const html = renderToStaticMarkup(
        <Input
          id="email-input"
          label="Email Address"
          error="Invalid email"
          helperText="We will never share your email"
        />,
      );
      expect(html).toContain('for="email-input"');
      expect(html).toContain('id="email-input"');
      expect(html).toContain('aria-invalid="true"');
      expect(html).toContain(
        'aria-describedby="email-input-error email-input-helper"',
      );
      expect(html).toContain('role="alert"');
      expect(html).toContain("Invalid email");
    });

    it("Select renders options and accessible chevron", () => {
      const html = renderToStaticMarkup(
        <Select
          id="role-select"
          label="Choose Role"
          options={[
            { value: "fe", label: "Frontend" },
            { value: "be", label: "Backend" },
          ]}
        />,
      );
      expect(html).toContain('for="role-select"');
      expect(html).toContain('<option value="fe">Frontend</option>');
      expect(html).toContain('<option value="be">Backend</option>');
    });

    it("Textarea renders character count and error", () => {
      const html = renderToStaticMarkup(
        <Textarea
          id="bio"
          label="Bio"
          value="Hello"
          readOnly
          maxLength={100}
          showCount
        />,
      );
      expect(html).toContain("5/100");
      expect(html).toContain("<textarea");
    });

    it("Checkbox renders label and description", () => {
      const html = renderToStaticMarkup(
        <Checkbox id="terms" label="I agree" description="Read terms" />,
      );
      expect(html).toContain('type="checkbox"');
      expect(html).toContain("I agree");
      expect(html).toContain("Read terms");
    });
  });

  describe("Modal / Dialog", () => {
    it("renders dialog with role and aria-modal when isOpen is true", () => {
      const html = renderToStaticMarkup(
        <Modal isOpen={true} onClose={() => {}} title="Delete Item">
          <p>Are you sure?</p>
        </Modal>,
      );
      expect(html).toContain('role="dialog"');
      expect(html).toContain('aria-modal="true"');
      expect(html).toContain("Delete Item");
      expect(html).toContain("Are you sure?");
    });

    it("returns null when isOpen is false", () => {
      const html = renderToStaticMarkup(
        <Modal isOpen={false} onClose={() => {}} title="Hidden">
          <p>Hidden content</p>
        </Modal>,
      );
      expect(html).toBe("");
    });
  });

  describe("Avatar & Status", () => {
    it("renders fallback initials when src is missing", () => {
      const html = renderToStaticMarkup(
        <Avatar alt="Ahmad Radwan" size="md" status="online" />,
      );
      expect(html).toContain("AR");
      expect(html).toContain('title="Status: online"');
      expect(html).toContain("bg-success");
    });
  });

  describe("Badges & Spinners", () => {
    it("Badge renders variant styles", () => {
      const html = renderToStaticMarkup(
        <Badge variant="success">Active</Badge>,
      );
      expect(html).toContain("Active");
      expect(html).toContain("text-success");
    });

    it("Spinner has accessible role and label", () => {
      const html = renderToStaticMarkup(
        <Spinner size="md" label="Loading data" />,
      );
      expect(html).toContain('role="status"');
      expect(html).toContain('aria-label="Loading data"');
    });
  });

  describe("EmptyState & Tabs", () => {
    it("EmptyState renders title and description", () => {
      const html = renderToStaticMarkup(
        <EmptyState
          title="No items found"
          description="Try broadening your search"
        />,
      );
      expect(html).toContain("No items found");
      expect(html).toContain("Try broadening your search");
    });

    it("Tabs renders role=tablist and tab elements", () => {
      const html = renderToStaticMarkup(
        <Tabs
          tabs={[
            { id: "tab1", label: "Tab 1", content: <p>Panel 1</p> },
            { id: "tab2", label: "Tab 2", content: <p>Panel 2</p> },
          ]}
        />,
      );
      expect(html).toContain('role="tablist"');
      expect(html).toContain('role="tab"');
      expect(html).toContain('role="tabpanel"');
      expect(html).toContain("Panel 1");
    });
  });
});
