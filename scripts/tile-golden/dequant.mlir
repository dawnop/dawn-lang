cuda_tile.module @m {
  entry @dequant(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %3 = broadcast %2 : tile<1x1xi32> -> tile<64x64xi32>
    %4 = iota : tile<64xi32>
    %5 = reshape %4 : tile<64xi32> -> tile<64x1xi32>
    %6 = broadcast %5 : tile<64x1xi32> -> tile<64x64xi32>
    %7 = addi %3, %6 : tile<64x64xi32>
    %8 = iota : tile<64xi32>
    %9 = reshape %8 : tile<64xi32> -> tile<1x64xi32>
    %10 = broadcast %9 : tile<1x64xi32> -> tile<64x64xi32>
    %11 = constant <i32: 0> : tile<64x64xi32>
    %12 = muli %10, %11 : tile<64x64xi32>
    %13 = addi %7, %12 : tile<64x64xi32>
    %14 = constant <i32: 16> : tile<64x64xi32>
    %15 = divi %13, %14 signed : tile<64x64xi32>
    %16 = constant <i32: 4> : tile<64x64xi32>
    %17 = muli %15, %16 : tile<64x64xi32>
    %18 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %19 = broadcast %18 : tile<1x1xi32> -> tile<64x64xi32>
    %20 = iota : tile<64xi32>
    %21 = reshape %20 : tile<64xi32> -> tile<64x1xi32>
    %22 = broadcast %21 : tile<64x1xi32> -> tile<64x64xi32>
    %23 = constant <i32: 0> : tile<64x64xi32>
    %24 = muli %22, %23 : tile<64x64xi32>
    %25 = addi %19, %24 : tile<64x64xi32>
    %26 = iota : tile<64xi32>
    %27 = reshape %26 : tile<64xi32> -> tile<1x64xi32>
    %28 = broadcast %27 : tile<1x64xi32> -> tile<64x64xi32>
    %29 = addi %25, %28 : tile<64x64xi32>
    %30 = divi %29, %14 signed : tile<64x64xi32>
    %31 = addi %17, %30 : tile<64x64xi32>
    %32 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %33 = make_tensor_view %32, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %34 = make_partition_view %33 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %35, %36, %37 = get_tile_block_id : tile<i32>
    %38, %39, %40 = get_tile_block_id : tile<i32>
    %41, %42 = load_view_tko weak %34[%35, %39] token=%0 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x64xf64>, token
    %43 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %44 = broadcast %43 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %45 = offset %44, %31 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %46, %47 = load_ptr_tko weak %45 token=%42 : tile<64x64xptr<f64>> -> tile<64x64xf64>, token
    %48 = mulf %41, %46 rounding<nearest_even> : tile<64x64xf64>
    %49 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %50 = make_tensor_view %49, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %51 = make_partition_view %50 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %52 = store_view_tko weak %48, %51[%35, %39] token=%47 : tile<64x64xf64>, partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
