cuda_tile.module @m {
  entry @attn_bwd_ds(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 64> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf64>, token
    %14 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %15 = make_tensor_view %14, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %17, %18 = load_view_tko weak %16[%9] token=%13 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf64>, token
    %19 = mulf %17, %12 rounding<nearest_even> : tile<64xf64>
    %20 = reduce %19 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%21: tile<f64>, %22: tile<f64>) {
      %23 = addf %21, %22 rounding<nearest_even> : tile<f64>
      yield %23 : tile<f64>
    }
    %24 = reshape %20 : tile<f64> -> tile<1xf64>
    %25 = broadcast %24 : tile<1xf64> -> tile<64xf64>
    %26 = mulf %12, %25 rounding<nearest_even> : tile<64xf64>
    %27 = subf %19, %26 rounding<nearest_even> : tile<64xf64>
    %28 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %29 = make_tensor_view %28, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %30 = make_partition_view %29 : partition_view<tile=(64), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %31 = store_view_tko weak %27, %30[%9] token=%18 : tile<64xf64>, partition_view<tile=(64), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
