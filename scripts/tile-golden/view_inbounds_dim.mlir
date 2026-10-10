cuda_tile.module @m {
  entry @view_inbounds_dim(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = offset %arg0, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %3 = make_tensor_view %2, shape = [100, 64], strides = [64, 1] : tensor_view<100x64xf64, strides=[64, 1]>
    %4 = make_partition_view %3 : partition_view<tile=(32x32), tensor_view<100x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %5 = offset %arg1, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %6 = make_tensor_view %5, shape = [100, 64], strides = [64, 1] : tensor_view<100x64xf64, strides=[64, 1]>
    %7 = make_partition_view %6 : partition_view<tile=(32x32), tensor_view<100x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %8, %9, %10 = get_tile_block_id : tile<i32>
    %11, %12, %13 = get_tile_block_id : tile<i32>
    %14, %15 = load_view_tko weak %4[%8, %12] token=%0 inbounds=[false, true] : partition_view<tile=(32x32), tensor_view<100x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %16 = store_view_tko weak %14, %7[%8, %12] token=%15 inbounds=[false, true] : tile<32x32xf64>, partition_view<tile=(32x32), tensor_view<100x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
