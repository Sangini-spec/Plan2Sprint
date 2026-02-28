import Hero from "@/components/landing/hero";
import SocialProof from "@/components/landing/social-proof";
import Problems from "@/components/landing/problems";
import Features from "@/components/landing/features";
import HowItWorks from "@/components/landing/how-it-works";
import Solutions from "@/components/landing/solutions";
import IntegrationsSection from "@/components/landing/integrations";
import PricingSection from "@/components/landing/pricing";
import AboutSection from "@/components/landing/about";
import TestimonialsSection from "@/components/landing/testimonials";
import ContactSection from "@/components/landing/contact";

export default function LandingPage() {
  return (
    <main>
      <Hero />
      <SocialProof />
      <Problems />
      <Features />
      <HowItWorks />
      <Solutions />
      <IntegrationsSection />
      <PricingSection />
      <AboutSection />
      <TestimonialsSection />
      <ContactSection />
    </main>
  );
}
