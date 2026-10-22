"""Pipeline A dạng service: upload CSV ảnh crawl -> lọc / kiểm duyệt tự động -> CSV quyết định.

Tách hẳn khỏi API truy xuất (api/): tiến trình, image Docker và port riêng (8100), vì cần torch +
SigLIP2 + LightGBM, còn API truy xuất chạy không torch.
"""
