"""
Invoice Parsers — KeToanBackEnd
Copied from TapHoa39BackEnd/services/invoice_parsers.py
Handles XML files from GDT (hoadondientu.gdt.gov.vn)
"""

import logging
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


class TaxInvoiceXMLParser:
    @staticmethod
    def parse(xml_content: bytes) -> Tuple[List[Dict], List[str]]:
        invoices = []
        errors = []
        try:
            root = ET.fromstring(xml_content)
            root_tag = root.tag.split('}')[-1] if '}' in root.tag else root.tag

            if root_tag == 'HDon':
                dlhdon = None
                for elem in root:
                    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                    if tag == 'DLHDon':
                        dlhdon = elem
                        break
                target = dlhdon if dlhdon is not None else root
                inv = TaxInvoiceXMLParser._parse_single_invoice(target)
                if inv:
                    invoices.append(inv)
            elif root_tag in ('HoaDonDienTu', 'Invoice'):
                inv = TaxInvoiceXMLParser._parse_single_invoice(root)
                if inv:
                    invoices.append(inv)
            else:
                found_any = False
                for elem in root.iter():
                    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                    if tag == 'HDon':
                        found_any = True
                        dlhdon = None
                        for child in elem:
                            ct = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                            if ct == 'DLHDon':
                                dlhdon = child
                                break
                        target = dlhdon if dlhdon is not None else elem
                        inv = TaxInvoiceXMLParser._parse_single_invoice(target)
                        if inv:
                            invoices.append(inv)
                    elif tag in ('HoaDonDienTu', 'Invoice', 'DLHDon'):
                        found_any = True
                        inv = TaxInvoiceXMLParser._parse_single_invoice(elem)
                        if inv:
                            invoices.append(inv)
                if not found_any:
                    inv = TaxInvoiceXMLParser._parse_single_invoice(root)
                    if inv:
                        invoices.append(inv)

            if not invoices:
                errors.append("Không tìm thấy hóa đơn trong file XML")

        except ET.ParseError as e:
            errors.append(f"Lỗi parse XML: {str(e)}")
        except Exception as e:
            errors.append(f"Lỗi xử lý file: {str(e)}")

        return invoices, errors

    @staticmethod
    def _parse_single_invoice(hdon_element) -> Optional[Dict]:
        try:
            invoice = {}

            def find_text(parent, *paths):
                for path in paths:
                    for elem in parent.iter():
                        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                        if tag == path and elem.text:
                            return elem.text.strip()
                return ''

            def find_in_section(parent, section_names, *paths):
                for elem in parent.iter():
                    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                    if tag in section_names:
                        result = find_text(elem, *paths)
                        if result:
                            return result
                    elif tag == 'NDHDon':
                        for child in elem.iter():
                            ct = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                            if ct in section_names:
                                result = find_text(child, *paths)
                                if result:
                                    return result
                return find_text(parent, *paths)

            def find_in_seller(parent, *paths):
                return find_in_section(parent, ('NBan', 'BenBan', 'NguoiBan', 'Seller', 'NCC'), *paths)

            def find_in_ttchung(parent, *paths):
                return find_in_section(parent, ('TTChung', 'ThongTinChung', 'GeneralInfo', 'Header'), *paths)

            def find_in_ttoan(parent, *paths):
                return find_in_section(parent, ('TToan', 'ThanhToan', 'TongHop', 'Summary', 'Payment'), *paths)

            def find_direct_child_text(parent, *tag_names):
                for child in parent:
                    ct = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if ct in tag_names and child.text:
                        return child.text.strip()
                return ''

            def find_in_ttkhac(parent, *field_names):
                for child in parent:
                    ct = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if ct == 'TTKhac':
                        for ttin in child:
                            ttag = ttin.tag.split('}')[-1] if '}' in ttin.tag else ttin.tag
                            if ttag != 'TTin':
                                continue
                            ttruong_el = dlieu_el = None
                            for sub in ttin:
                                st = sub.tag.split('}')[-1] if '}' in sub.tag else sub.tag
                                if st == 'TTruong':
                                    ttruong_el = sub
                                elif st == 'DLieu':
                                    dlieu_el = sub
                            if ttruong_el is not None and ttruong_el.text and dlieu_el is not None and dlieu_el.text:
                                if ttruong_el.text.strip() in field_names:
                                    return dlieu_el.text.strip()
                return ''

            invoice['invoiceNo'] = find_in_ttchung(hdon_element, 'SHDon', 'SoHoaDon', 'So', 'InvoiceNo', 'InvoiceNumber')
            if not invoice['invoiceNo']:
                invoice['invoiceNo'] = find_text(hdon_element, 'SHDon', 'SoHoaDon', 'So', 'InvoiceNo', 'InvoiceNumber')

            khmshdon = find_in_ttchung(hdon_element, 'KHMSHDon')
            khhdon = find_in_ttchung(hdon_element, 'KHHDon', 'KyHieu', 'KyHieuHoaDon', 'SerialNo', 'Symbol', 'MauSo')
            invoice['invoiceSymbol'] = (khmshdon or '') + (khhdon or '')

            date_str = find_in_ttchung(hdon_element, 'NLap', 'NgayLap', 'Ngay', 'InvoiceDate', 'Date', 'TDLap')
            if not date_str:
                date_str = find_text(hdon_element, 'NLap', 'NgayLap', 'Ngay', 'InvoiceDate', 'Date')
            invoice['invoiceDate'] = TaxInvoiceXMLParser._normalize_date(date_str)

            invoice['sellerTaxCode'] = find_in_seller(hdon_element, 'MST', 'MaSoThue', 'TaxCode', 'SellerTaxCode', 'MSTNBan')
            invoice['sellerName'] = find_in_seller(hdon_element, 'Ten', 'TenDonVi', 'TenNguoiBan', 'TenCty', 'CompanyName', 'SellerName', 'TenNBan', 'TenNCC', 'supplierName')
            invoice['sellerAddress'] = find_in_seller(hdon_element, 'DChi', 'DiaChi', 'Address', 'DChiNBan')
            invoice['sellerPhone'] = find_in_seller(hdon_element, 'SDThoai', 'DThoai', 'Phone', 'SellerPhone')
            invoice['sellerEmail'] = find_in_seller(hdon_element, 'DCTDTu', 'Email', 'SellerEmail')

            nmua_section = None
            for elem in hdon_element.iter():
                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                if tag == 'NMua':
                    nmua_section = elem
                    break

            if nmua_section is not None:
                invoice['buyerTaxCode'] = find_text(nmua_section, 'MST', 'MaSoThue', 'TaxCode')
                invoice['buyerName'] = find_text(nmua_section, 'Ten', 'TenDonVi', 'TenNguoiMua')
                invoice['buyerAddress'] = find_text(nmua_section, 'DChi', 'DiaChi', 'Address')
                invoice['buyerCode'] = find_text(nmua_section, 'MKHang', 'MaKH', 'BuyerCode')
            else:
                invoice['buyerTaxCode'] = find_in_section(hdon_element, ('NMua', 'BenMua', 'NguoiMua', 'Buyer'), 'MST', 'MaSoThue', 'TaxCode', 'MSTNMua')
                invoice['buyerName'] = find_in_section(hdon_element, ('NMua', 'BenMua', 'NguoiMua', 'Buyer'), 'Ten', 'TenDonVi', 'TenNguoiMua', 'TenNMua', 'BuyerName')
                invoice['buyerAddress'] = find_in_section(hdon_element, ('NMua', 'BenMua', 'NguoiMua', 'Buyer'), 'DChi', 'DiaChi', 'Address', 'DChiNMua')
                invoice['buyerCode'] = find_in_section(hdon_element, ('NMua', 'BenMua', 'NguoiMua', 'Buyer'), 'MKHang', 'MaKH', 'BuyerCode')

            before_vat_str = find_in_ttoan(hdon_element, 'TgTCThue', 'TgTHang', 'TienHang', 'TotalBeforeVat', 'SubTotal', 'THTTLTSuat')
            if not before_vat_str:
                before_vat_str = find_text(hdon_element, 'TgTCThue', 'TgTHang', 'TienHang', 'TotalBeforeVat')
            invoice['totalBeforeVat'] = TaxInvoiceXMLParser._parse_amount(before_vat_str)

            vat_str = find_in_ttoan(hdon_element, 'TgTThue', 'TgThue', 'TienThueGTGT', 'TienThue', 'TThue', 'VatAmount', 'TaxAmount')
            if not vat_str:
                vat_str = find_text(hdon_element, 'TgTThue', 'TgThue', 'TienThueGTGT', 'TienThue', 'VatAmount')
            invoice['vatAmount'] = TaxInvoiceXMLParser._parse_amount(vat_str)

            vat_rate_str = ''
            for elem in hdon_element.iter():
                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                if tag == 'LTSuat':
                    for child in elem:
                        ct = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if ct == 'TSuat' and child.text:
                            vat_rate_str = child.text.strip()
                            break
                    if vat_rate_str:
                        break
            if not vat_rate_str:
                for elem in hdon_element.iter():
                    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                    if tag in ('HHDVu', 'HHDV'):
                        for child in elem:
                            ct = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                            if ct == 'TSuat' and child.text:
                                vat_rate_str = child.text.strip()
                                break
                        if vat_rate_str:
                            break
            if vat_rate_str:
                try:
                    invoice['vatRate'] = float(vat_rate_str.replace('%', '').strip())
                except ValueError:
                    invoice['vatRate'] = 0
            else:
                invoice['vatRate'] = 0

            total_str = find_in_ttoan(hdon_element, 'TgTTTBSo', 'TongTienThanhToan', 'TongTien', 'TgTTTBQT', 'TTCKTMai', 'TotalAmount', 'GrandTotal')
            if not total_str:
                total_str = find_text(hdon_element, 'TgTTTBSo', 'TongTienThanhToan', 'TongTien', 'TotalAmount')
            invoice['totalAmount'] = TaxInvoiceXMLParser._parse_amount(total_str)
            invoice['totalAmountInWords'] = find_in_ttoan(hdon_element, 'TgTTTBChu', 'VietBangChu', 'InWords')

            invoice['items'] = []
            dshhdv_element = None
            for elem in hdon_element.iter():
                tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                if tag in ('DSHHDV', 'DSHHDVu'):
                    dshhdv_element = elem
                    break

            if dshhdv_element is not None:
                for hhdv_element in dshhdv_element:
                    tag = hhdv_element.tag.split('}')[-1] if '}' in hhdv_element.tag else hhdv_element.tag
                    if tag not in ('HHDV', 'HHDVu'):
                        continue
                    stt_str = find_direct_child_text(hhdv_element, 'STT') or '0'
                    try:
                        stt = int(float(stt_str))
                    except ValueError:
                        stt = 0
                    item_name = find_direct_child_text(hhdv_element, 'THHDVu', 'THHDV', 'TenHang') or ''
                    item_unit = find_direct_child_text(hhdv_element, 'DVTinh', 'DonViTinh') or ''
                    item_quantity = TaxInvoiceXMLParser._parse_amount(find_direct_child_text(hhdv_element, 'SLuong', 'SoLuong'))
                    item_unit_price = TaxInvoiceXMLParser._parse_amount(find_direct_child_text(hhdv_element, 'DGia', 'DonGia'))
                    item_amount = TaxInvoiceXMLParser._parse_amount(find_direct_child_text(hhdv_element, 'ThTien', 'ThanhTien'))
                    item_tax_amount = TaxInvoiceXMLParser._parse_amount(find_direct_child_text(hhdv_element, 'TThue', 'TienThue'))
                    if item_tax_amount == 0:
                        item_tax_amount = TaxInvoiceXMLParser._parse_amount(find_in_ttkhac(hhdv_element, 'VATAmount', 'VATAmountOC'))
                    ttkhac_amount = TaxInvoiceXMLParser._parse_amount(find_in_ttkhac(hhdv_element, 'Amount', 'AmountOC'))
                    item_amount_after_tax = ttkhac_amount if ttkhac_amount > item_amount else item_amount + item_tax_amount
                    invoice['items'].append({
                        'stt': stt,
                        'name': item_name,
                        'unit': item_unit,
                        'quantity': item_quantity,
                        'unitPrice': item_unit_price,
                        'amount': item_amount,
                        'taxAmount': item_tax_amount,
                        'amountAfterTax': item_amount_after_tax,
                        'vatRate': find_direct_child_text(hhdv_element, 'TSuat', 'ThueSuat')
                    })

            if not invoice['invoiceNo']:
                return None
            return invoice

        except Exception as e:
            logger.error(f"Error parsing invoice element: {e}")
            return None

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        if not date_str:
            return ''
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y%m%d', '%d.%m.%Y'):
            try:
                return datetime.strptime(date_str[:10], fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue
        return date_str

    @staticmethod
    def _parse_amount(amount_str: str) -> float:
        if not amount_str:
            return 0.0
        try:
            cleaned = re.sub(r'[^\d.,]', '', amount_str)
            if ',' in cleaned and '.' in cleaned:
                cleaned = cleaned.replace('.', '').replace(',', '.')
            elif ',' in cleaned:
                cleaned = cleaned.replace(',', '.')
            return float(cleaned)
        except ValueError:
            return 0.0
