cuda_tile.module @m {
  entry @xattn_context(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 2048> : tile<i32>
    %5 = muli %3, %4 : tile<i32>
    %6, %7, %8 = get_tile_block_id : tile<i32>
    %9 = constant <i32: 2048> : tile<i32>
    %10 = muli %6, %9 : tile<i32>
    %11 = addi %5, %10 : tile<i32>
    %12 = constant <f64: 0.0> : tile<32x32xf64>
    %13 = constant <i32: 0> : tile<i32>
    %14 = constant <i32: 2> : tile<i32>
    %15 = constant <i32: 1> : tile<i32>
    %16 = for %17 in (%13 to %14, step %15) : tile<i32> iter_values(%18 = %12) -> (tile<32x32xf64>) {
      %19 = constant <i32: 32> : tile<i32>
      %20 = muli %17, %19 : tile<i32>
      %21 = addi %11, %20 : tile<i32>
      %22 = reshape %21 : tile<i32> -> tile<1x1xi32>
      %23 = broadcast %22 : tile<1x1xi32> -> tile<32x32xi32>
      %24 = iota : tile<32xi32>
      %25 = reshape %24 : tile<32xi32> -> tile<32x1xi32>
      %26 = broadcast %25 : tile<32x1xi32> -> tile<32x32xi32>
      %27 = constant <i32: 64> : tile<32x32xi32>
      %28 = muli %26, %27 : tile<32x32xi32>
      %29 = addi %23, %28 : tile<32x32xi32>
      %30 = iota : tile<32xi32>
      %31 = reshape %30 : tile<32xi32> -> tile<1x32xi32>
      %32 = broadcast %31 : tile<1x32xi32> -> tile<32x32xi32>
      %33 = addi %29, %32 : tile<32x32xi32>
      %34 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %35 = broadcast %34 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %36 = offset %35, %33 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %37, %38 = load_ptr_tko weak %36 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %39 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %40 = make_tensor_view %39, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
      %41 = make_partition_view %40 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
      %42, %43, %44 = get_tile_block_id : tile<i32>
      %45, %46 = load_view_tko weak %41[%17, %44] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %47 = mmaf %37, %45, %18 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %47 : tile<32x32xf64>
    }
    %48 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %49 = make_tensor_view %48, shape = [32, 64], strides = [64, 1] : tensor_view<32x64xf64, strides=[64, 1]>
    %50 = make_partition_view %49 : partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %51, %52, %53 = get_tile_block_id : tile<i32>
    %54, %55, %56 = get_tile_block_id : tile<i32>
    %57 = store_view_tko weak %16, %50[%51, %56] token=%0 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<32x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
