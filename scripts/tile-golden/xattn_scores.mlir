cuda_tile.module @m {
  entry @xattn_scores(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [32, 64], strides = [64, 1] : tensor_view<32x64xf64, strides=[64, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %3[%4, %9] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %12 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %13 = make_tensor_view %12, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %14 = make_partition_view %13 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %15, %16, %17 = get_tile_block_id : tile<i32>
    %18, %19 = load_view_tko weak %14[%16, %9] token=%11 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %20 = permute %18 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
    %21 = constant <f64: 0.0> : tile<32x32xf64>
    %22 = mmaf %10, %20, %21 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %23 = constant <f64: 0.17677669529663687> : tile<32x32xf64>
    %24 = mulf %22, %23 rounding<nearest_even> : tile<32x32xf64>
    %25 = reshape %24 : tile<32x32xf64> -> tile<1x32x32xf64>
    %26 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %27 = make_tensor_view %26, shape = [2, 32, 64], strides = [2048, 64, 1] : tensor_view<2x32x64xf64, strides=[2048, 64, 1]>
    %28 = make_partition_view %27 : partition_view<tile=(1x32x32), padding_value = zero, tensor_view<2x32x64xf64, strides=[2048, 64, 1]>, dim_map=[0, 1, 2]>
    %29 = store_view_tko weak %25, %28[%9, %4, %16] token=%19 : tile<1x32x32xf64>, partition_view<tile=(1x32x32), padding_value = zero, tensor_view<2x32x64xf64, strides=[2048, 64, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
