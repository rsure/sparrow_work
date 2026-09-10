// 模块说明：递归遍历文件时的附带统计（对应 Python tool_utils.WalkStats）。
package com.example.backendjava.tools;

/**
 * 一次目录遍历的统计数据。
 *
 * <p>工具在返回结果里把这三项告诉模型/用户，避免"统计数字偏小"被误解成目录就这么大。</p>
 */
public class WalkStats {

    /** 因命中依赖/缓存目录名（node_modules、.git 等）而被整体跳过的目录个数。 */
    private int skippedDirs;

    /** 因属于系统文件/系统目录而被跳过的条目个数；目录按 1 个计，不展开。 */
    private int skippedSystem;

    /** 是否因为达到文件数上限而提前停止；true 表示统计结果不完整。 */
    private boolean truncated;

    /** 返回被跳过的依赖/缓存目录个数。 */
    public int getSkippedDirs() {
        return skippedDirs;
    }

    /** 累加一个被跳过的依赖/缓存目录。 */
    public void addSkippedDir() {
        skippedDirs++;
    }

    /** 返回被跳过的系统文件/目录个数。 */
    public int getSkippedSystem() {
        return skippedSystem;
    }

    /** 累加一个被跳过的系统文件/目录。 */
    public void addSkippedSystem() {
        skippedSystem++;
    }

    /** 返回是否因达到上限而截断。 */
    public boolean isTruncated() {
        return truncated;
    }

    /** 标记本次遍历已经截断（后续数字都不完整）。 */
    public void markTruncated() {
        truncated = true;
    }
}
