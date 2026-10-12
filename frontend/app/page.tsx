import { ClosingCta } from "@/components/landing/closing-cta";
import { Hero } from "@/components/landing/hero";
import { HowItWorks } from "@/components/landing/how-it-works";
import { PlatformFeatures } from "@/components/landing/platform-features";
import { ProductPreview } from "@/components/landing/product-preview";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

export default function Home() {
  return (
    <>
      <SiteHeader />
      <main className="flex-1">
        <Hero />
        <ProductPreview />
        <HowItWorks />
        <PlatformFeatures />
        <ClosingCta />
      </main>
      <SiteFooter />
    </>
  );
}
