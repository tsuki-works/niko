const CAD = new Intl.NumberFormat('en-CA', {
  style: 'currency',
  currency: 'CAD',
});

export function formatCAD(amount: number): string {
  return CAD.format(amount);
}
