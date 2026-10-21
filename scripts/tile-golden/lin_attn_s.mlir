cuda_tile.module @m {
  entry @lin_attn_s(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <f64: 0.0> : tile<32x32xf64>
    %2 = constant <i32: 0> : tile<i32>
    %3 = constant <i32: 2> : tile<i32>
    %4 = constant <i32: 1> : tile<i32>
    %5 = for %6 in (%2 to %3, step %4) : tile<i32> iter_values(%7 = %1) -> (tile<32x32xf64>) {
      %8 = assume div_by<16>, %arg0 : tile<ptr<f64>>
      %9 = make_tensor_view %8, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
      %10 = make_partition_view %9 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
      %11, %12, %13 = get_tile_block_id : tile<i32>
      %14, %15 = load_view_tko weak %10[%6, %11] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %16 = permute %14 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
      %17 = constant <f64: 0.0> : tile<32x32xf64>
      %18 = cmpf greater_than ordered %16, %17 : tile<32x32xf64> -> tile<32x32xi1>
      %19 = constant <f64: 1.0> : tile<32x32xf64>
      %20 = addf %16, %19 rounding<nearest_even> : tile<32x32xf64>
      %21 = exp %16 : tile<32x32xf64>
      %22 = select %18, %20, %21 : tile<32x32xi1>, tile<32x32xf64>
      %23 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %24 = make_tensor_view %23, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
      %25 = make_partition_view %24 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
      %26, %27, %28 = get_tile_block_id : tile<i32>
      %29, %30 = load_view_tko weak %25[%6, %27] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %31 = mmaf %22, %29, %7 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %31 : tile<32x32xf64>
    }
    %32 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %33 = make_tensor_view %32, shape = [32, 32], strides = [32, 1] : tensor_view<32x32xf64, strides=[32, 1]>
    %34 = make_partition_view %33 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %35, %36, %37 = get_tile_block_id : tile<i32>
    %38, %39, %40 = get_tile_block_id : tile<i32>
    %41 = store_view_tko weak %5, %34[%35, %39] token=%0 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<32x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
