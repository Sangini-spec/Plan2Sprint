"use client";

import { useRef, useState } from "react";
import { motion, useInView } from "framer-motion";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Calendar,
  HeadphonesIcon,
  Handshake,
  Mail,
  Loader2,
  CheckCircle2,
  Send,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button, GlassCard, SectionLabel, SectionHeading } from "@/components/ui";

/* -------------------------------------------------------------------------- */
/*  Zod Schema                                                                 */
/* -------------------------------------------------------------------------- */

const contactSchema = z.object({
  fullName: z.string().min(2, "Full name must be at least 2 characters"),
  workEmail: z
    .string()
    .min(1, "Work email is required")
    .email("Please enter a valid email address"),
  teamSize: z.string().min(1, "Please select your team size"),
  interest: z.string().min(1, "Please select what you're interested in"),
  message: z
    .string()
    .min(10, "Message must be at least 10 characters")
    .max(2000, "Message must be under 2000 characters"),
});

type ContactFormData = z.infer<typeof contactSchema>;

/* -------------------------------------------------------------------------- */
/*  Data                                                                       */
/* -------------------------------------------------------------------------- */

const teamSizeOptions = [
  { value: "", label: "Select team size" },
  { value: "1-10", label: "1\u201310 people" },
  { value: "11-50", label: "11\u201350 people" },
  { value: "51-200", label: "51\u2013200 people" },
  { value: "200+", label: "200+ people" },
];

const interestOptions = [
  { value: "demo", label: "Demo" },
  { value: "trial", label: "Trial support" },
  { value: "enterprise", label: "Enterprise pricing" },
  { value: "partnership", label: "Partnership" },
  { value: "other", label: "Other" },
];

interface ContactChannel {
  icon: React.ReactNode;
  label: string;
  detail: string;
}

const contactChannels: ContactChannel[] = [
  {
    icon: <Calendar className="h-5 w-5" />,
    label: "Sales",
    detail:
      "Book a 30-minute demo with our team. We\u2019ll walk through how Plan2Sprint fits your workflow and answer every question.",
  },
  {
    icon: <HeadphonesIcon className="h-5 w-5" />,
    label: "Support",
    detail:
      "For existing customers. Response within 4 business hours on weekdays. We\u2019re here to help you get the most out of Plan2Sprint.",
  },
  {
    icon: <Handshake className="h-5 w-5" />,
    label: "Partnerships",
    detail:
      "Integration partnerships, reseller enquiries, and technology alliances. Let\u2019s build something great together.",
  },
  {
    icon: <Mail className="h-5 w-5" />,
    label: "General",
    detail: "hello@plan2sprint.com",
  },
];

/* -------------------------------------------------------------------------- */
/*  Social Icons                                                               */
/* -------------------------------------------------------------------------- */

function LinkedInIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
  );
}

function GitHubIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
    </svg>
  );
}

function XIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z" />
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/*  Floating Label Input                                                       */
/* -------------------------------------------------------------------------- */

interface FloatingFieldProps {
  id: string;
  label: string;
  error?: string;
  children: React.ReactNode;
  /** When true, render the label as a non-form-bound caption (used for
   * radio groups, where ``<label htmlFor>`` referencing a single id is
   * incorrect — there is no single form control to point at). */
  asGroup?: boolean;
}

function FieldWrapper({ id, label, error, children, asGroup }: FloatingFieldProps) {
  // For radio / checkbox groups we use ``<fieldset>``/``<legend>`` so
  // assistive tech announces the group name when any individual radio
  // is focused, and ``<label for>`` doesn't dangle.
  if (asGroup) {
    return (
      <fieldset className="relative border-0 p-0 m-0">
        <legend className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          {label}
        </legend>
        {children}
        {error && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-1.5 text-xs font-medium text-red-500"
          >
            {error}
          </motion.p>
        )}
      </fieldset>
    );
  }

  return (
    <div className="relative">
      <label
        htmlFor={id}
        className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]"
      >
        {label}
      </label>
      {children}
      {error && (
        <motion.p
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-1.5 text-xs font-medium text-red-500"
        >
          {error}
        </motion.p>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Contact Form                                                               */
/* -------------------------------------------------------------------------- */

function ContactForm() {
  const [submitted, setSubmitted] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
  } = useForm<ContactFormData>({
    resolver: zodResolver(contactSchema),
    mode: "onBlur",
  });

  const onSubmit = async (_data: ContactFormData) => {
    // Simulate API call
    await new Promise((resolve) => setTimeout(resolve, 1500));
    setSubmitted(true);
    reset();
  };

  if (submitted) {
    return (
      <GlassCard
        whileHover={{ y: 0 }}
        className="flex flex-col items-center justify-center text-center min-h-[400px]"
      >
        <motion.div
          initial={{ scale: 0.5, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        >
          <CheckCircle2 className="h-16 w-16 text-[var(--color-brand-secondary)] mb-4" />
        </motion.div>
        <h3 className="text-xl font-bold text-[var(--text-primary)]">
          Message sent!
        </h3>
        <p className="mt-2 text-sm text-[var(--text-secondary)] max-w-xs">
          We&rsquo;ll be in touch within 1 business day.
        </p>
        <Button
          variant="ghost"
          size="sm"
          className="mt-6"
          onClick={() => setSubmitted(false)}
        >
          Send another message
        </Button>
      </GlassCard>
    );
  }

  const inputClasses = cn(
    "w-full rounded-xl px-4 py-3 text-sm",
    "bg-[var(--bg-surface)] text-[var(--text-primary)]",
    "border border-[var(--border-subtle)]",
    "placeholder:text-[var(--text-secondary)]/50",
    "transition-all duration-200",
    "focus:outline-none focus:ring-2 focus:ring-[var(--color-brand-secondary)]/40 focus:border-[var(--color-brand-secondary)]/60"
  );

  const errorInputClasses = "border-red-500/60 focus:ring-red-500/40 focus:border-red-500/60";

  return (
    <GlassCard whileHover={{ y: 0 }}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-5" noValidate>
        {/* Full Name */}
        <FieldWrapper
          id="fullName"
          label="Full Name *"
          error={errors.fullName?.message}
        >
          <input
            id="fullName"
            type="text"
            autoComplete="name"
            placeholder="Your full name"
            className={cn(inputClasses, errors.fullName && errorInputClasses)}
            {...register("fullName")}
          />
        </FieldWrapper>

        {/* Work Email */}
        <FieldWrapper
          id="workEmail"
          label="Work Email *"
          error={errors.workEmail?.message}
        >
          <input
            id="workEmail"
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            className={cn(inputClasses, errors.workEmail && errorInputClasses)}
            {...register("workEmail")}
          />
        </FieldWrapper>

        {/* Team Size */}
        <FieldWrapper
          id="teamSize"
          label="Company / Team Size"
          error={errors.teamSize?.message}
        >
          <select
            id="teamSize"
            autoComplete="organization"
            className={cn(
              inputClasses,
              "appearance-none pr-10 cursor-pointer",
              errors.teamSize && errorInputClasses
            )}
            style={{
              backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%239090A8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E")`,
              backgroundSize: "16px",
              backgroundPosition: "right 12px center",
              backgroundRepeat: "no-repeat",
            }}
            defaultValue=""
            {...register("teamSize")}
          >
            {teamSizeOptions.map((opt) => (
              <option key={opt.value} value={opt.value} disabled={!opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </FieldWrapper>

        {/* Interest — radio group, rendered as <fieldset><legend> so the
            label isn't dangling on a non-existent ``id``. */}
        <FieldWrapper
          id="interest"
          label="I'm interested in... *"
          error={errors.interest?.message}
          asGroup
        >
          <div className="flex flex-wrap gap-3 mt-1">
            {interestOptions.map((opt) => (
              <label
                key={opt.value}
                className={cn(
                  "relative flex items-center gap-2 cursor-pointer",
                  "rounded-lg px-3 py-2 text-sm",
                  "border border-[var(--border-subtle)]",
                  "bg-[var(--bg-surface)] text-[var(--text-secondary)]",
                  "transition-all duration-200",
                  "hover:border-[var(--color-brand-secondary)]/40 hover:bg-[var(--color-brand-secondary)]/5",
                  "has-[:checked]:border-[var(--color-brand-secondary)]/60 has-[:checked]:bg-[var(--color-brand-secondary)]/10 has-[:checked]:text-[var(--color-brand-secondary)]"
                )}
              >
                <input
                  type="radio"
                  value={opt.value}
                  className="sr-only"
                  {...register("interest")}
                />
                <span className="text-sm font-medium">{opt.label}</span>
              </label>
            ))}
          </div>
        </FieldWrapper>

        {/* Message */}
        <FieldWrapper
          id="message"
          label="Message *"
          error={errors.message?.message}
        >
          <textarea
            id="message"
            rows={4}
            autoComplete="off"
            placeholder="Tell us about your team and what you're looking for..."
            className={cn(
              inputClasses,
              "resize-none",
              errors.message && errorInputClasses
            )}
            {...register("message")}
          />
        </FieldWrapper>

        {/* Submit */}
        <Button
          type="submit"
          variant="primary"
          size="lg"
          className="w-full"
          disabled={isSubmitting}
        >
          {isSubmitting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Sending...
            </>
          ) : (
            <>
              <Send className="h-4 w-4" />
              Send Message
            </>
          )}
        </Button>
      </form>
    </GlassCard>
  );
}

/* -------------------------------------------------------------------------- */
/*  Section                                                                    */
/* -------------------------------------------------------------------------- */

export default function ContactSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const isInView = useInView(sectionRef, { once: true, margin: "-100px" });

  return (
    <section
      id="contact"
      ref={sectionRef}
      className="relative py-24 sm:py-32 overflow-hidden"
    >
      <div className="relative mx-auto max-w-7xl px-6 lg:px-8">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={isInView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className="mx-auto max-w-2xl text-center mb-16"
        >
          <SectionLabel>CONTACT US</SectionLabel>
          <SectionHeading className="mt-2">
            Let&rsquo;s talk about your team.
          </SectionHeading>
        </motion.div>

        {/* Two-column layout */}
        <div className="grid gap-12 lg:grid-cols-2 lg:gap-16">
          {/* Left: Contact options */}
          <motion.div
            initial={{ opacity: 0, x: -30 }}
            animate={isInView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.7, ease: "easeOut", delay: 0.15 }}
            className="space-y-6"
          >
            {contactChannels.map((channel) => (
              <div
                key={channel.label}
                className={cn(
                  "flex items-start gap-4 rounded-xl p-4",
                  "transition-colors duration-200",
                  "hover:bg-[var(--bg-surface-raised)]/50"
                )}
              >
                <div
                  className={cn(
                    "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
                    "bg-[var(--color-brand-secondary)]/10 text-[var(--color-brand-secondary)]"
                  )}
                >
                  {channel.icon}
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                    {channel.label}
                  </h3>
                  <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
                    {channel.detail}
                  </p>
                </div>
              </div>
            ))}

            {/* Social links */}
            <div className="pt-6 border-t border-[var(--border-subtle)]">
              <p className="mb-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                Follow us
              </p>
              <div className="flex items-center gap-4">
                {[
                  {
                    icon: <LinkedInIcon className="h-5 w-5" />,
                    label: "LinkedIn",
                    href: "#",
                  },
                  {
                    icon: <GitHubIcon className="h-5 w-5" />,
                    label: "GitHub",
                    href: "#",
                  },
                  {
                    icon: <XIcon className="h-5 w-5" />,
                    label: "X",
                    href: "#",
                  },
                ].map((social) => (
                  <a
                    key={social.label}
                    href={social.href}
                    aria-label={social.label}
                    className={cn(
                      "flex h-10 w-10 items-center justify-center rounded-lg",
                      "text-[var(--text-secondary)]",
                      "border border-[var(--border-subtle)]",
                      "transition-all duration-200",
                      "hover:text-[var(--color-brand-secondary)] hover:border-[var(--color-brand-secondary)]/30 hover:bg-[var(--color-brand-secondary)]/5"
                    )}
                  >
                    {social.icon}
                  </a>
                ))}
              </div>
            </div>
          </motion.div>

          {/* Right: Contact form */}
          <motion.div
            initial={{ opacity: 0, x: 30 }}
            animate={isInView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.7, ease: "easeOut", delay: 0.3 }}
          >
            <ContactForm />
          </motion.div>
        </div>
      </div>
    </section>
  );
}
