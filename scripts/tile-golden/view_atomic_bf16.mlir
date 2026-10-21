cuda_tile.module @m {
  entry @view_atomic_bf16(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<bf16>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_tile_block_id : tile<i32>
    %5 = constant <i32: 64> : tile<i32>
    %6 = muli %2, %5 : tile<i32>
    %7 = reshape %6 : tile<i32> -> tile<1x1xi32>
    %8 = broadcast %7 : tile<1x1xi32> -> tile<16x64xi32>
    %9 = iota : tile<16xi32>
    %10 = reshape %9 : tile<16xi32> -> tile<16x1xi32>
    %11 = broadcast %10 : tile<16x1xi32> -> tile<16x64xi32>
    %12 = constant <i32: 0> : tile<16x64xi32>
    %13 = muli %11, %12 : tile<16x64xi32>
    %14 = addi %8, %13 : tile<16x64xi32>
    %15 = iota : tile<64xi32>
    %16 = reshape %15 : tile<64xi32> -> tile<1x64xi32>
    %17 = broadcast %16 : tile<1x64xi32> -> tile<16x64xi32>
    %18 = addi %14, %17 : tile<16x64xi32>
    %19 = constant <i32: 500> : tile<16x64xi32>
    %20 = cmpi less_than %18, %19, signed : tile<16x64xi32> -> tile<16x64xi1>
    %21 = constant <i32: -1> : tile<16x64xi32>
    %22 = reshape %arg0 : tile<ptr<i32>> -> tile<1x1xptr<i32>>
    %23 = broadcast %22 : tile<1x1xptr<i32>> -> tile<16x64xptr<i32>>
    %24 = offset %23, %18 : tile<16x64xptr<i32>>, tile<16x64xi32> -> tile<16x64xptr<i32>>
    %25, %26 = load_ptr_tko weak %24, %20, %21 token=%0 : tile<16x64xptr<i32>>, tile<16x64xi1>, tile<16x64xi32> -> tile<16x64xi32>, token
    %27 = constant <i32: 0> : tile<i32>
    %28 = reshape %27 : tile<i32> -> tile<1x1xi32>
    %29 = broadcast %28 : tile<1x1xi32> -> tile<16x64xi32>
    %30 = iota : tile<16xi32>
    %31 = reshape %30 : tile<16xi32> -> tile<16x1xi32>
    %32 = broadcast %31 : tile<16x1xi32> -> tile<16x64xi32>
    %33 = addi %29, %32 : tile<16x64xi32>
    %34 = iota : tile<64xi32>
    %35 = reshape %34 : tile<64xi32> -> tile<1x64xi32>
    %36 = broadcast %35 : tile<1x64xi32> -> tile<16x64xi32>
    %37 = constant <i32: 0> : tile<16x64xi32>
    %38 = muli %36, %37 : tile<16x64xi32>
    %39 = addi %33, %38 : tile<16x64xi32>
    %40 = cmpi equal %25, %39, signed : tile<16x64xi32> -> tile<16x64xi1>
    %41 = exti %40 unsigned : tile<16x64xi1> -> tile<16x64xi32>
    %42 = reduce %41 dim=1 identities=[0 : i32] : tile<16x64xi32> -> tile<16xi32> (%43: tile<i32>, %44: tile<i32>) {
      %45 = addi %43, %44 : tile<i32>
      yield %45 : tile<i32>
    }
    %46 = assume div_by<16>, %arg1 : tile<ptr<bf16>>
    %47 = offset %46, %1 : tile<ptr<bf16>>, tile<i32> -> tile<ptr<bf16>>
    %48 = make_tensor_view %47, shape = [16], strides = [1] : tensor_view<16xbf16, strides=[1]>
    %49 = make_strided_view %48 : strided_view<tile=(16), traversal_strides=[16], tensor_view<16xbf16, strides=[1]>, dim_map=[0]>
    %50 = itof %42 signed rounding<nearest_even> : tile<16xi32> -> tile<16xbf16>
    %51 = atomic_red_view_tko relaxed device %49[%1], addf, %50 token=%0 : tile<16xbf16>, strided_view<tile=(16), traversal_strides=[16], tensor_view<16xbf16, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
