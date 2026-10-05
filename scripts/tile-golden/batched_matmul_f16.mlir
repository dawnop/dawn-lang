cuda_tile.module @m {
  entry @batched_matmul_f16(%arg0: tile<ptr<f16>>, %arg1: tile<ptr<f16>>, %arg2: tile<ptr<f16>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10 = constant <i32: 1024> : tile<i32>
    %11 = muli %9, %10 : tile<i32>
    %12 = constant <i32: 512> : tile<i32>
    %13 = muli %1, %12 : tile<i32>
    %14 = addi %11, %13 : tile<i32>
    %15 = constant <i32: 1024> : tile<i32>
    %16 = muli %9, %15 : tile<i32>
    %17 = constant <i32: 16> : tile<i32>
    %18 = muli %5, %17 : tile<i32>
    %19 = addi %16, %18 : tile<i32>
    %20 = constant <f16: 0.0> : tile<16x16xf16>
    %21 = constant <i32: 0> : tile<i32>
    %22 = constant <i32: 2> : tile<i32>
    %23 = constant <i32: 1> : tile<i32>
    %24, %25 = for %26 in (%21 to %22, step %23) : tile<i32> iter_values(%27 = %20, %28 = %0) -> (tile<16x16xf16>, token) {
      %29 = constant <i32: 16> : tile<i32>
      %30 = muli %26, %29 : tile<i32>
      %31 = addi %14, %30 : tile<i32>
      %32 = reshape %31 : tile<i32> -> tile<1x1xi32>
      %33 = broadcast %32 : tile<1x1xi32> -> tile<16x16xi32>
      %34 = iota : tile<16xi32>
      %35 = reshape %34 : tile<16xi32> -> tile<16x1xi32>
      %36 = broadcast %35 : tile<16x1xi32> -> tile<16x16xi32>
      %37 = constant <i32: 32> : tile<16x16xi32>
      %38 = muli %36, %37 : tile<16x16xi32>
      %39 = addi %33, %38 : tile<16x16xi32>
      %40 = iota : tile<16xi32>
      %41 = reshape %40 : tile<16xi32> -> tile<1x16xi32>
      %42 = broadcast %41 : tile<1x16xi32> -> tile<16x16xi32>
      %43 = addi %39, %42 : tile<16x16xi32>
      %44 = reshape %arg0 : tile<ptr<f16>> -> tile<1x1xptr<f16>>
      %45 = broadcast %44 : tile<1x1xptr<f16>> -> tile<16x16xptr<f16>>
      %46 = offset %45, %43 : tile<16x16xptr<f16>>, tile<16x16xi32> -> tile<16x16xptr<f16>>
      %47, %48 = load_ptr_tko weak %46 token=%28 : tile<16x16xptr<f16>> -> tile<16x16xf16>, token
      %49 = constant <i32: 512> : tile<i32>
      %50 = muli %26, %49 : tile<i32>
      %51 = addi %19, %50 : tile<i32>
      %52 = reshape %51 : tile<i32> -> tile<1x1xi32>
      %53 = broadcast %52 : tile<1x1xi32> -> tile<16x16xi32>
      %54 = iota : tile<16xi32>
      %55 = reshape %54 : tile<16xi32> -> tile<16x1xi32>
      %56 = broadcast %55 : tile<16x1xi32> -> tile<16x16xi32>
      %57 = constant <i32: 32> : tile<16x16xi32>
      %58 = muli %56, %57 : tile<16x16xi32>
      %59 = addi %53, %58 : tile<16x16xi32>
      %60 = iota : tile<16xi32>
      %61 = reshape %60 : tile<16xi32> -> tile<1x16xi32>
      %62 = broadcast %61 : tile<1x16xi32> -> tile<16x16xi32>
      %63 = addi %59, %62 : tile<16x16xi32>
      %64 = reshape %arg1 : tile<ptr<f16>> -> tile<1x1xptr<f16>>
      %65 = broadcast %64 : tile<1x1xptr<f16>> -> tile<16x16xptr<f16>>
      %66 = offset %65, %63 : tile<16x16xptr<f16>>, tile<16x16xi32> -> tile<16x16xptr<f16>>
      %67, %68 = load_ptr_tko weak %66 token=%48 : tile<16x16xptr<f16>> -> tile<16x16xf16>, token
      %69 = mmaf %47, %67, %27 : tile<16x16xf16>, tile<16x16xf16>, tile<16x16xf16>
      continue %69, %68 : tile<16x16xf16>, token
    }
    %70 = reshape %24 : tile<16x16xf16> -> tile<1x16x16xf16>
    %71 = assume div_by<16>, %arg2 : tile<ptr<f16>>
    %72 = make_tensor_view %71, shape = [2, 32, 32], strides = [1024, 32, 1] : tensor_view<2x32x32xf16, strides=[1024, 32, 1]>
    %73 = make_partition_view %72 : partition_view<tile=(1x16x16), padding_value = zero, tensor_view<2x32x32xf16, strides=[1024, 32, 1]>, dim_map=[0, 1, 2]>
    %74, %75, %76 = get_tile_block_id : tile<i32>
    %77, %78, %79 = get_tile_block_id : tile<i32>
    %80, %81, %82 = get_tile_block_id : tile<i32>
    %83 = store_view_tko weak %70, %73[%76, %77, %81] token=%25 : tile<1x16x16xf16>, partition_view<tile=(1x16x16), padding_value = zero, tensor_view<2x32x32xf16, strides=[1024, 32, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
