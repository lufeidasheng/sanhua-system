import os
import logging

logging.basicConfig(
    format='[%(asctime)s] %(levelname)s - %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

def fix_certificates(base_path):
    logging.info("开始检测证书文件...")

    certs_path = os.path.join(base_path, "certs")
    required_certs = ["eventbus.crt", "ca-bundle.crt"]

    if not os.path.exists(certs_path):
        logging.warning(f"证书目录不存在，尝试创建：{certs_path}")
        os.makedirs(certs_path)

    for cert_name in required_certs:
        cert_file = os.path.join(certs_path, cert_name)
        if not os.path.isfile(cert_file):
            logging.error(f"缺失证书文件: {cert_file}")
            # 这里可以添加自动生成或从安全位置复制证书的逻辑
            # 示例：生成占位证书文件（仅示范）
            with open(cert_file, "w") as f:
                f.write("PLACEHOLDER CERTIFICATE CONTENT")
            logging.info(f"已创建占位证书文件: {cert_file}")
        else:
            logging.info(f"证书文件存在: {cert_file}")

    logging.info("证书检测完成。")

if __name__ == "__main__":
    # 方便单独测试，传入项目根路径
    fix_certificates(os.path.abspath(os.path.dirname(__file__)))
