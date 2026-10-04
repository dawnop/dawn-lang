cuda_tile.module @m {
  entry @lin_attn_s(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<32x32xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 2> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5, %6 = for %7 in (%2 to %3, step %4) : tile<i32> iter_values(%8 = %1, %9 = %0) -> (tile<32x32xf64>, token) {
      %10 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %11 = make_tensor_view %10, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
      %12 = make_partition_view %11 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
      %13, %14, %15 = get_tile_block_id : tile<i32>
      %16, %17 = load_view_tko weak %12[%7, %13] token=%9 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %18 = permute %16 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
      %19 = constant <f64: 0.0> : tile<32x32xf64>
      %20 = cmpf greater_than ordered %18, %19 : tile<32x32xf64> -> tile<32x32xi1>
      %21 = constant <f64: 1.0> : tile<32x32xf64>
      %22 = addf %18, %21 rounding<nearest_even> : tile<32x32xf64>
      %23 = exp %18 : tile<32x32xf64>
      %24 = select %20, %22, %23 : tile<32x32xi1>, tile<32x32xf64>
      %25 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %26 = make_tensor_view %25, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
      %27 = make_partition_view %26 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
      %28, %29, %30 = get_tile_block_id : tile<i32>
      %31, %32 = load_view_tko weak %27[%7, %29] token=%17 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %33 = mmaf %24, %31, %8 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %33, %32 : tile<32x32xf64>, token
    }
    %34 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %35 = make_tensor_view %34, shape = [32, 32], strides = [32, 1] : tensor_view<32x32xf64, strides=[32, 1]>
    %36 = make_partition_view %35 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %37, %38, %39 = get_tile_block_id : tile<i32>
    %40, %41, %42 = get_tile_block_id : tile<i32>
    %43 = store_view_tko weak %5, %36[%37, %41] token=%6 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
